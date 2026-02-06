import { useCallback, useEffect, useMemo, useState } from 'react';
import { Activity, Bell, Maximize2, RefreshCw, TrendingUp, X } from 'lucide-react';
import { apiClient } from '../api/client';
import { useStore } from '../store/useStore';
import { StockChart } from './StockChart';
import { MiniChat } from './MiniChat';

type RightPanelTab = 'alerts' | 'portfolio' | 'chart';

type WatchlistItem = {
  ticker: string;
  label: string;
  price?: number | null;
  change?: number | null;
  changePct?: number | null;
};

type RightPanelProps = {
  onCollapse: () => void;
  onSubscribeClick?: () => void;
  showMiniChat?: boolean;
  className?: string;
};

const DEFAULT_USER_ID = 'default_user';

const parsePricePayload = (payload: any): { price?: number; change?: number; changePct?: number } => {
  if (!payload) return {};
  if (typeof payload === 'object' && payload.price) {
    return {
      price: Number(payload.price),
      change: payload.change !== undefined ? Number(payload.change) : undefined,
      changePct: payload.change_percent !== undefined ? Number(payload.change_percent) : undefined,
    };
  }

  const text = typeof payload === 'string' ? payload : String(payload);
  const priceMatch = text.match(/Current Price:\s*\$([0-9.,]+)/i);
  const changeMatch = text.match(/Change:\s*([+-]?[0-9.]+)/i);
  const pctMatch = text.match(/\(([-+]?[0-9.]+)%\)/);
  const fallbackPrice = text.match(/\$([0-9]+(?:\.[0-9]+)?)/);

  return {
    price: priceMatch ? Number(priceMatch[1].replace(/,/g, '')) : fallbackPrice ? Number(fallbackPrice[1]) : undefined,
    change: changeMatch ? Number(changeMatch[1]) : undefined,
    changePct: pctMatch ? Number(pctMatch[1]) : undefined,
  };
};

const formatPct = (value?: number | null) => {
  if (value === undefined || value === null || Number.isNaN(value)) return '--';
  const sign = value >= 0 ? '+' : '';
  return `${sign}${value.toFixed(2)}%`;
};

const TabButton: React.FC<{
  active: boolean;
  onClick: () => void;
  title: string;
  icon: React.ReactNode;
  badge?: number;
  testId?: string;
}> = ({ active, onClick, title, icon, badge, testId }) => (
  <button
    type="button"
    title={title}
    onClick={onClick}
    data-testid={testId}
    className={`relative p-2 rounded-lg transition-colors ${
      active ? 'bg-fin-primary/10 text-fin-primary' : 'text-fin-muted hover:text-fin-text hover:bg-fin-hover'
    }`}
  >
    {icon}
    {badge !== undefined && badge > 0 && (
      <span className="absolute -top-0.5 -right-0.5 w-4 h-4 bg-fin-danger text-white text-[9px] font-bold rounded-full flex items-center justify-center">
        {badge > 9 ? '9+' : badge}
      </span>
    )}
  </button>
);

export const RightPanel: React.FC<RightPanelProps> = ({
  onCollapse,
  onSubscribeClick,
  showMiniChat = true,
  className,
}) => {
  const [activeTab, setActiveTab] = useState<RightPanelTab>('alerts');
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);
  const [alerts, setAlerts] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [chartHeight, setChartHeight] = useState(250);
  const [isChartMaximized, setIsChartMaximized] = useState(false);
  const [isPortfolioEditing, setIsPortfolioEditing] = useState(false);
  const [positionDrafts, setPositionDrafts] = useState<Record<string, string>>({});

  const { subscriptionEmail, portfolioPositions, setPortfolioPosition, removePortfolioPosition } = useStore();

  const loadWatchlist = useCallback(async () => {
    try {
      const profile = await apiClient.getUserProfile(DEFAULT_USER_ID);
      const list = Array.isArray(profile?.profile?.watchlist) ? profile.profile.watchlist : [];
      if (!list.length) {
        setWatchlist([]);
        return;
      }

      const results = await Promise.all(
        list.map(async (ticker: string) => {
          try {
            const response = await apiClient.fetchStockPrice(ticker);
            const payload = response?.data ?? response;
            const parsed = parsePricePayload(payload?.data ?? payload);
            return { ticker, label: ticker, ...parsed } as WatchlistItem;
          } catch {
            return { ticker, label: ticker } as WatchlistItem;
          }
        }),
      );
      setWatchlist(results);
    } catch {
      setWatchlist([]);
    }
  }, []);

  const loadAlerts = useCallback(async () => {
    if (!subscriptionEmail) {
      setAlerts([]);
      return;
    }
    try {
      const response = await apiClient.listSubscriptions(subscriptionEmail);
      setAlerts(Array.isArray(response?.subscriptions) ? response.subscriptions : []);
    } catch {
      setAlerts([]);
    }
  }, [subscriptionEmail]);

  const refreshAll = useCallback(async () => {
    setLoading(true);
    await Promise.all([loadWatchlist(), loadAlerts()]);
    setLastUpdated(new Date());
    setLoading(false);
  }, [loadWatchlist, loadAlerts]);

  useEffect(() => {
    refreshAll();
    const timer = setInterval(refreshAll, 60000);
    return () => clearInterval(timer);
  }, [refreshAll]);

  useEffect(() => {
    const onEsc = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setIsChartMaximized(false);
    };
    window.addEventListener('keydown', onEsc);
    return () => window.removeEventListener('keydown', onEsc);
  }, []);

  const positionRows = useMemo(() => {
    return watchlist.map((item) => {
      const key = item.ticker.trim().toUpperCase();
      const shares = portfolioPositions[key] || 0;
      const price = typeof item.price === 'number' ? item.price : undefined;
      const change = typeof item.change === 'number' ? item.change : undefined;
      const changePct = typeof item.changePct === 'number' ? item.changePct : undefined;
      const value = price !== undefined ? price * shares : 0;
      const dayChange =
        change !== undefined
          ? change * shares
          : price !== undefined && changePct !== undefined
            ? (price * shares * changePct) / 100
            : 0;
      return { ...item, ticker: key, shares, value, dayChange };
    });
  }, [watchlist, portfolioPositions]);

  const portfolioSummary = useMemo(() => {
    const holdings = positionRows.filter((item) => item.shares > 0);
    if (!holdings.length) return null;
    const totalValue = holdings.reduce((sum, item) => sum + item.value, 0);
    const dayChange = holdings.reduce((sum, item) => sum + item.dayChange, 0);
    const avgChange = totalValue ? (dayChange / totalValue) * 100 : 0;
    return { holdings, holdingsCount: holdings.length, totalValue, dayChange, avgChange };
  }, [positionRows]);

  const startPortfolioEdit = () => {
    const drafts = watchlist.reduce<Record<string, string>>((acc, item) => {
      const key = item.ticker.trim().toUpperCase();
      const shares = portfolioPositions[key];
      acc[key] = shares ? String(shares) : '';
      return acc;
    }, {});
    setPositionDrafts(drafts);
    setIsPortfolioEditing(true);
  };

  const cancelPortfolioEdit = () => {
    setIsPortfolioEditing(false);
    setPositionDrafts({});
  };

  const savePortfolioEdit = () => {
    watchlist.forEach((item) => {
      const key = item.ticker.trim().toUpperCase();
      const raw = positionDrafts[key];
      const value = Number(raw);
      if (Number.isFinite(value) && value > 0) {
        setPortfolioPosition(key, value);
      } else if (raw !== undefined) {
        removePortfolioPosition(key);
      }
    });
    setIsPortfolioEditing(false);
  };

  const renderAlerts = () => (
    <div className="flex-1 overflow-y-auto p-3 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-fin-text-secondary">订阅提醒</span>
        <span className="text-[10px] text-fin-muted bg-fin-bg px-1.5 rounded">{alerts.length} 条</span>
      </div>
      <div className="space-y-2">
        {alerts.slice(0, 10).map((item: any, idx: number) => (
          <div key={`${item.ticker || 't'}-${idx}`} className="border-b border-fin-border/50 pb-2 last:border-0">
            <div className="text-xs font-semibold text-fin-text">{item.ticker || '--'} 触发提醒</div>
            <div className="text-[10px] text-fin-text-secondary">{(item.alert_types || []).join(', ') || '--'}</div>
          </div>
        ))}
        {!alerts.length && <div className="text-xs text-fin-muted py-4 text-center">暂无订阅提醒</div>}
      </div>
      <button
        type="button"
        onClick={onSubscribeClick}
        className="w-full py-2 border border-dashed border-fin-border rounded-lg text-xs text-fin-text-secondary hover:text-fin-primary hover:border-fin-primary transition-colors"
      >
        + 管理订阅规则
      </button>
    </div>
  );

  const renderPortfolio = () => (
    <div className="flex-1 overflow-y-auto p-3 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-fin-text-secondary">资产组合</span>
        <button
          type="button"
          onClick={() => (isPortfolioEditing ? savePortfolioEdit() : startPortfolioEdit())}
          className="text-[10px] px-2 py-0.5 rounded-full border border-fin-border text-fin-muted hover:text-fin-primary hover:border-fin-primary transition-colors"
        >
          {isPortfolioEditing ? 'Save' : 'Edit'}
        </button>
      </div>

      {isPortfolioEditing ? (
        <div className="space-y-3">
          {positionRows.length > 0 ? (
            <div className="space-y-2">
              {positionRows.map((item) => (
                <div key={item.ticker} className="flex items-center justify-between gap-2 text-xs">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-fin-text">{item.ticker}</span>
                    <span className="text-[10px] text-fin-muted">
                      {typeof item.price === 'number' ? `$${item.price.toFixed(2)}` : '--'}
                    </span>
                  </div>
                  <input
                    type="number"
                    inputMode="decimal"
                    min="0"
                    step="0.01"
                    value={positionDrafts[item.ticker] ?? ''}
                    onChange={(event) =>
                      setPositionDrafts((prev) => ({ ...prev, [item.ticker]: event.target.value }))
                    }
                    className="w-20 px-2 py-1 rounded border border-fin-border bg-fin-bg text-fin-text text-right text-xs focus:outline-none focus:border-fin-primary"
                    placeholder="0"
                  />
                </div>
              ))}
            </div>
          ) : (
            <div className="text-xs text-fin-muted">Add watchlist tickers to set holdings.</div>
          )}
          <div className="flex items-center justify-between text-[10px] text-fin-muted">
            <span>Blank or 0 removes a position.</span>
            <button type="button" onClick={cancelPortfolioEdit} className="hover:text-fin-text">
              Cancel
            </button>
          </div>
        </div>
      ) : portfolioSummary ? (
        <div className="space-y-3">
          <div className="space-y-1">
            <div className="text-xl font-bold text-fin-text">${portfolioSummary.totalValue.toLocaleString()}</div>
            <div className={`text-sm font-medium ${portfolioSummary.dayChange >= 0 ? 'text-fin-success' : 'text-fin-danger'}`}>
              {portfolioSummary.dayChange >= 0 ? '+' : ''}
              {portfolioSummary.dayChange.toFixed(2)} ({formatPct(portfolioSummary.avgChange)})
            </div>
            <div className="text-[10px] text-fin-muted">Holdings {portfolioSummary.holdingsCount}</div>
          </div>
          <div className="space-y-2">
            {portfolioSummary.holdings.map((item) => (
              <div key={item.ticker} className="flex items-center justify-between text-xs">
                <div className="flex flex-col">
                  <span className="font-semibold text-fin-text">{item.ticker}</span>
                  <span className="text-[10px] text-fin-muted">
                    {item.shares} shares{typeof item.price === 'number' ? ` @ $${item.price.toFixed(2)}` : ''}
                  </span>
                </div>
                <div className="text-right">
                  <div className="text-fin-text">${item.value.toLocaleString()}</div>
                  <div className={`text-[10px] ${item.dayChange >= 0 ? 'text-fin-success' : 'text-fin-danger'}`}>
                    {item.dayChange >= 0 ? '+' : ''}
                    {item.dayChange.toFixed(2)}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="text-xs text-fin-muted py-4 text-center">Set holdings to generate portfolio summary.</div>
      )}
    </div>
  );

  const renderChart = () => (
    <div className="flex-1 overflow-hidden p-3 flex flex-col">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold text-fin-text-secondary">Market Chart</span>
        <button
          type="button"
          onClick={() => setIsChartMaximized(true)}
          className="p-1 hover:bg-fin-hover rounded text-fin-muted hover:text-fin-primary transition-colors"
          title="全屏查看"
        >
          <Maximize2 size={12} />
        </button>
      </div>
      <div className="flex-1 relative min-h-0">
        <div style={{ height: chartHeight }} className="w-full bg-fin-bg-secondary/50 rounded-lg overflow-hidden">
          <StockChart />
        </div>
        <div
          className="absolute bottom-0 left-0 right-0 h-3 cursor-ns-resize bg-gradient-to-t from-fin-border/30 to-transparent flex items-center justify-center"
          onMouseDown={(event) => {
            const startY = event.clientY;
            const startHeight = chartHeight;
            const onMouseMove = (moveEvent: MouseEvent) => {
              const diff = moveEvent.clientY - startY;
              setChartHeight(Math.max(150, Math.min(500, startHeight + diff)));
            };
            const onMouseUp = () => {
              document.removeEventListener('mousemove', onMouseMove);
              document.removeEventListener('mouseup', onMouseUp);
            };
            document.addEventListener('mousemove', onMouseMove);
            document.addEventListener('mouseup', onMouseUp);
          }}
        >
          <div className="w-8 h-1 bg-fin-border rounded-full" />
        </div>
      </div>
    </div>
  );

  return (
    <section
      data-testid="context-panel"
      className={`flex flex-col h-full bg-fin-card border border-fin-border rounded-xl shadow-sm overflow-hidden ${className || ''}`}
    >
      <div className="flex items-center justify-between px-2 py-1.5 border-b border-fin-border bg-fin-bg/50">
        <div className="flex items-center gap-1">
          <TabButton
            active={activeTab === 'alerts'}
            onClick={() => setActiveTab('alerts')}
            title="消息中心"
            icon={<Bell size={14} />}
            badge={alerts.length}
            testId="context-tab-alerts"
          />
          <TabButton
            active={activeTab === 'portfolio'}
            onClick={() => setActiveTab('portfolio')}
            title="资产组合"
            icon={<Activity size={14} />}
            testId="context-tab-portfolio"
          />
          <TabButton
            active={activeTab === 'chart'}
            onClick={() => setActiveTab('chart')}
            title="市场图表"
            icon={<TrendingUp size={14} />}
            testId="context-tab-chart"
          />
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={refreshAll}
            className="p-1.5 hover:bg-fin-hover rounded text-fin-muted hover:text-fin-text transition-colors"
            title="Refresh"
          >
            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
          </button>
          <button
            type="button"
            onClick={onCollapse}
            className="p-1.5 hover:bg-fin-hover rounded text-fin-muted hover:text-fin-text transition-colors"
            title="Collapse"
          >
            <X size={12} />
          </button>
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-hidden">
        {activeTab === 'alerts' && renderAlerts()}
        {activeTab === 'portfolio' && renderPortfolio()}
        {activeTab === 'chart' && renderChart()}
      </div>

      {showMiniChat && (
        <div className="h-[45%] min-h-[180px] border-t border-fin-border flex flex-col">
          <MiniChat />
        </div>
      )}

      {lastUpdated && (
        <div className="text-[10px] text-fin-muted text-center py-1 border-t border-fin-border/50 shrink-0">
          上次更新: {lastUpdated.toLocaleTimeString()}
        </div>
      )}

      {isChartMaximized && (
        <div className="fixed inset-0 z-[100] bg-black/80 backdrop-blur-sm flex items-center justify-center p-6">
          <div className="bg-fin-panel border border-fin-border rounded-xl w-full max-w-5xl h-[80vh] flex flex-col shadow-2xl">
            <div className="flex items-center justify-between p-4 border-b border-fin-border/50">
              <div className="flex items-center gap-2">
                <TrendingUp className="text-fin-primary" size={20} />
                <span className="font-bold text-lg text-fin-text">Market Chart (Full View)</span>
              </div>
              <button
                type="button"
                onClick={() => setIsChartMaximized(false)}
                className="p-2 hover:bg-fin-hover rounded-full text-fin-muted hover:text-fin-text transition-colors"
              >
                <X size={20} />
              </button>
            </div>
            <div className="flex-1 p-4 overflow-hidden bg-fin-bg-secondary/30">
              <StockChart />
            </div>
          </div>
        </div>
      )}
    </section>
  );
};
