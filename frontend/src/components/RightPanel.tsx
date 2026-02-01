import { useEffect, useMemo, useState, useCallback } from 'react';
import { apiClient } from '../api/client';
import { useStore } from '../store/useStore';
import { StockChart } from './StockChart';
import { AgentLogPanel } from './AgentLogPanel';
import { MiniChat } from './MiniChat';
import { Activity, Bell, RefreshCw, TrendingUp, X, Maximize2, Terminal } from 'lucide-react';

const DEFAULT_USER_ID = 'default_user';

const MARKET_TICKERS = [
  { label: 'S&P 500', ticker: '^GSPC' },
  { label: 'NASDAQ', ticker: '^IXIC' },
  { label: 'DOW', ticker: '^DJI' },
  { label: 'Gold', ticker: 'GC=F' },
  { label: 'BTC', ticker: 'BTC-USD' },
];

type Quote = {
  ticker: string;
  label: string;
  price?: number | null;
  change?: number | null;
  changePct?: number | null;
  raw?: string;
};

type WatchlistItem = Quote & { loading?: boolean };

const parsePriceText = (payload: any): { price?: number; change?: number; changePct?: number; raw?: string } => {
  if (!payload) return {};
  if (typeof payload === 'object' && payload.price) {
    return {
      price: Number(payload.price),
      change: payload.change !== undefined ? Number(payload.change) : undefined,
      changePct: payload.change_percent !== undefined ? Number(payload.change_percent) : undefined,
      raw: JSON.stringify(payload),
    };
  }
  const text = typeof payload === 'string' ? payload : String(payload);
  const priceMatch = text.match(/Current Price:\s*\$([0-9.,]+)/i);
  const changeMatch = text.match(/Change:\s*([+-]?[0-9.]+)/i);
  const pctMatch = text.match(/\(([-+]?[0-9.]+)%\)/);
  const fallbackPrice = text.match(/\$([0-9]+(?:\.[0-9]+)?)/);

  const price = priceMatch ? Number(priceMatch[1].replace(/,/g, '')) : fallbackPrice ? Number(fallbackPrice[1]) : undefined;
  const change = changeMatch ? Number(changeMatch[1]) : undefined;
  const changePct = pctMatch ? Number(pctMatch[1]) : undefined;
  return { price, change, changePct, raw: text };
};

const formatChangePct = (value?: number | null) => {
  if (value === undefined || value === null || Number.isNaN(value)) return '--';
  const sign = value >= 0 ? '+' : '';
  return `${sign}${value.toFixed(2)}%`;
};


// Tab types for the right panel (removed 'chat' as main area already has chat)
type RightPanelTab = 'alerts' | 'portfolio' | 'chart' | 'console';

// 触发记录类型
type TriggerRecord = {
  id: string;
  ticker: string;
  type: string;
  message: string;
  timestamp: number;
};

// Tab button component
const TabButton: React.FC<{
  icon: React.ReactNode;
  active: boolean;
  onClick: () => void;
  title: string;
  badge?: number;
}> = ({ icon, active, onClick, title, badge }) => (
  <button
    onClick={onClick}
    title={title}
    className={`relative p-2 rounded-lg transition-all ${
      active
        ? 'bg-fin-primary/10 text-fin-primary'
        : 'text-fin-muted hover:text-fin-text hover:bg-fin-hover'
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

export const RightPanel: React.FC<{ onCollapse: () => void; onSubscribeClick?: () => void; showMiniChat?: boolean }> = ({ onCollapse, onSubscribeClick, showMiniChat = true }) => {
  // Tab state - default to 'alerts' now
  const [activeTab, setActiveTab] = useState<RightPanelTab>('alerts');

  // 触发记录和未读计数
  const [triggerRecords, setTriggerRecords] = useState<TriggerRecord[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);

  const { subscriptionEmail, portfolioPositions, setPortfolioPosition, removePortfolioPosition } = useStore();
  const [, setMarketQuotes] = useState<Quote[]>([]);
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);
  const [alerts, setAlerts] = useState<any[]>([]);
  // Reserved for future agent diagnostics panel
  // const [orchestrator, setOrchestrator] = useState<any>(null);
  // const [health, setHealth] = useState<any>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [loading, setLoading] = useState(false);
  const [chartHeight, setChartHeight] = useState(250);
  const [isChartMaximized, setIsChartMaximized] = useState(false);
  const [isPortfolioEditing, setIsPortfolioEditing] = useState(false);
  const [positionDrafts, setPositionDrafts] = useState<Record<string, string>>({});

  // 监听全屏状态下的 ESC 用于退出
  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setIsChartMaximized(false);
    };
    window.addEventListener('keydown', handleEsc);
    return () => window.removeEventListener('keydown', handleEsc);
  }, []);

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

  const loadMarketQuotes = async () => {
    const results = await Promise.all(
      MARKET_TICKERS.map(async (item) => {
        try {
          const response = await apiClient.fetchStockPrice(item.ticker);
          const payload = response?.data ?? response;
          const parsed = parsePriceText(payload?.data ?? payload);
          return { ...item, ...parsed };
        } catch (error) {
          return { ...item, raw: 'error' };
        }
      })
    );
    setMarketQuotes(results);
  };

  const loadWatchlist = async () => {
    try {
      const profile = await apiClient.getUserProfile(DEFAULT_USER_ID);
      const list = Array.isArray(profile?.profile?.watchlist) ? profile.profile.watchlist : [];
      if (list.length === 0) {
        setWatchlist([]);
        return;
      }
      const results = await Promise.all(
        list.map(async (ticker: string) => {
          try {
            const response = await apiClient.fetchStockPrice(ticker);
            const payload = response?.data ?? response;
            const parsed = parsePriceText(payload?.data ?? payload);
            return { ticker, label: ticker, ...parsed };
          } catch (error) {
            return { ticker, label: ticker };
          }
        })
      );
      setWatchlist(results);
    } catch (error) {
      setWatchlist([]);
    }
  };

  const loadAlerts = async () => {
    if (!subscriptionEmail) {
      setAlerts([]);
      return;
    }
    try {
      const response = await apiClient.listSubscriptions(subscriptionEmail);
      setAlerts(Array.isArray(response?.subscriptions) ? response.subscriptions : []);
    } catch (error) {
      setAlerts([]);
    }
  };

  // 点击 alerts tab 时清除未读计数
  const handleAlertsTabClick = useCallback(() => {
    setActiveTab('alerts');
    setUnreadCount(0);
  }, []);

  // 删除触发记录
  const deleteTriggerRecord = useCallback((id: string) => {
    setTriggerRecords((prev) => prev.filter((record) => record.id !== id));
  }, []);

  // 模拟触发记录（实际应从后端获取）
  // TODO: 对接后端真实触发记录 API
  useEffect(() => {
    // 模拟一些触发记录用于展示
    const mockRecords: TriggerRecord[] = alerts.slice(0, 3).map((alert, idx) => ({
      id: `trigger-${Date.now()}-${idx}`,
      ticker: alert.ticker || 'UNKNOWN',
      type: (alert.alert_types || ['price_change'])[0],
      message: `${alert.ticker} 触发了 ${(alert.alert_types || []).join(', ')} 提醒`,
      timestamp: Date.now() - idx * 3600000,
    }));
    if (mockRecords.length > 0) {
      setTriggerRecords(mockRecords);
      // 只有不在 alerts tab 时才增加未读计数
      if (activeTab !== 'alerts') {
        setUnreadCount(mockRecords.length);
      }
    }
  }, [alerts]);

  // Reserved for future agent diagnostics panel
  // const loadDiagnostics = async () => {
  //   try {
  //     const [oc, health] = await Promise.all([
  //       apiClient.diagnosticsOrchestrator(),
  //       apiClient.healthCheck(),
  //     ]);
  //     setOrchestrator(oc);
  //     setHealth(health);
  //   } catch (error) {
  //     setOrchestrator(null);
  //     setHealth(null);
  //   }
  // };

  const refreshAll = async () => {
    setLoading(true);
    await Promise.all([loadMarketQuotes(), loadWatchlist(), loadAlerts()]);
    setLastUpdated(new Date());
    setLoading(false);
  };

  useEffect(() => {
    refreshAll();
    const timer = setInterval(refreshAll, 60000);
    return () => clearInterval(timer);
  }, [subscriptionEmail]);

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
    if (holdings.length === 0) return null;
    const totalValue = holdings.reduce((sum, item) => sum + item.value, 0);
    const dayChange = holdings.reduce((sum, item) => sum + item.dayChange, 0);
    const avgChange = totalValue ? (dayChange / totalValue) * 100 : 0;
    const topMover = [...holdings]
      .filter((item) => typeof item.changePct === 'number')
      .sort((a, b) => Math.abs((b.changePct || 0)) - Math.abs((a.changePct || 0)))[0];
    return { totalValue, dayChange, avgChange, topMover, holdingsCount: holdings.length };
  }, [positionRows]);

  // 从真实后端数据提取 Agent 状态 - Reserved for future agent status panel
  // const orchestratorStats = orchestrator?.data?.orchestrator_stats;
  // const sourceStats = orchestrator?.data?.by_source?.stock_price || [];

  // Tab content renderers
  const renderTabContent = () => {
    switch (activeTab) {
      case 'alerts':
        return (
          <div className="flex-1 overflow-y-auto p-3 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-fin-text-secondary">订阅提醒</span>
              <span className="text-[10px] text-fin-muted bg-fin-bg px-1.5 rounded">{alerts.length} 条</span>
            </div>
            <div className="space-y-2">
              {alerts.slice(0, 10).map((item, idx) => (
                <div key={idx} className="flex justify-between items-center border-b border-fin-border/50 pb-2 last:border-0">
                  <div className="flex gap-2 items-center">
                    <span className="text-fin-primary text-sm">🚀</span>
                    <div>
                      <div className="text-xs font-semibold text-fin-text">{item.ticker} 触发提醒</div>
                      <div className="text-[10px] text-fin-text-secondary">{(item.alert_types || []).join(', ')}</div>
                    </div>
                  </div>
                </div>
              ))}
              {alerts.length === 0 && <div className="text-xs text-fin-muted py-4 text-center">暂无订阅提醒</div>}
            </div>
            <button
              onClick={onSubscribeClick}
              className="w-full py-2 border border-dashed border-fin-border rounded-lg text-xs text-fin-text-secondary hover:text-fin-primary hover:border-fin-primary transition-colors"
            >
              + 管理订阅规则
            </button>

            {/* 触发记录区域 */}
            <div className="pt-3 border-t border-fin-border/50">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-semibold text-fin-text-secondary">触发记录</span>
                <span className="text-[10px] text-fin-muted bg-fin-bg px-1.5 rounded">{triggerRecords.length} 条</span>
              </div>
              <div className="space-y-2">
                {triggerRecords.map((record) => (
                  <div key={record.id} className="flex justify-between items-center bg-fin-bg/50 rounded-lg px-2 py-1.5 group">
                    <div className="flex gap-2 items-center flex-1 min-w-0">
                      <span className="text-fin-warning text-sm">⚡</span>
                      <div className="flex-1 min-w-0">
                        <div className="text-xs font-medium text-fin-text truncate">{record.ticker}</div>
                        <div className="text-[10px] text-fin-muted truncate">{record.message}</div>
                        <div className="text-[9px] text-fin-muted/70">
                          {new Date(record.timestamp).toLocaleString()}
                        </div>
                      </div>
                    </div>
                    <button
                      onClick={() => deleteTriggerRecord(record.id)}
                      className="p-1 text-fin-muted hover:text-fin-danger opacity-0 group-hover:opacity-100 transition-opacity"
                      title="删除记录"
                    >
                      <X size={12} />
                    </button>
                  </div>
                ))}
                {triggerRecords.length === 0 && (
                  <div className="text-xs text-fin-muted py-3 text-center">暂无触发记录</div>
                )}
              </div>
            </div>
          </div>
        );

      case 'portfolio':
        return (
          <div className="flex-1 overflow-y-auto p-3 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-fin-text-secondary">资产组合</span>
              <button
                onClick={() => {
                  if (isPortfolioEditing) {
                    savePortfolioEdit();
                  } else {
                    startPortfolioEdit();
                  }
                }}
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
                          onChange={(e) =>
                            setPositionDrafts((prev) => ({ ...prev, [item.ticker]: e.target.value }))
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
                  <button onClick={cancelPortfolioEdit} className="text-fin-muted hover:text-fin-text">Cancel</button>
                </div>
              </div>
            ) : portfolioSummary ? (
              <div className="space-y-3">
                <div className="space-y-1">
                  <div className="text-xl font-bold text-fin-text">${portfolioSummary.totalValue.toLocaleString()}</div>
                  <div className={`text-sm font-medium ${portfolioSummary.dayChange >= 0 ? 'text-fin-success' : 'text-fin-danger'}`}>
                    {portfolioSummary.dayChange >= 0 ? '+' : ''}{portfolioSummary.dayChange.toFixed(2)} ({formatChangePct(portfolioSummary.avgChange)})
                  </div>
                  <div className="text-[10px] text-fin-muted">Holdings {portfolioSummary.holdingsCount}</div>
                </div>
                <div className="space-y-2">
                  {positionRows.filter((item) => item.shares > 0).map((item) => (
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
                          {item.dayChange >= 0 ? '+' : ''}{item.dayChange.toFixed(2)}
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

      case 'chart':
        return (
          <div className="flex-1 overflow-hidden p-3 flex flex-col">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-semibold text-fin-text-secondary">Market Chart</span>
              <button
                onClick={() => setIsChartMaximized(true)}
                className="p-1 hover:bg-fin-hover rounded text-fin-muted hover:text-fin-primary transition-colors"
                title="全屏查看"
              >
                <Maximize2 size={12} />
              </button>
            </div>
            <div className="flex-1 relative min-h-0">
              <div
                style={{ height: chartHeight }}
                className="w-full bg-fin-bg-secondary/50 rounded-lg overflow-hidden"
              >
                <StockChart />
              </div>
              {/* 拉伸手柄 */}
              <div
                className="absolute bottom-0 left-0 right-0 h-3 cursor-ns-resize bg-gradient-to-t from-fin-border/30 to-transparent flex items-center justify-center"
                onMouseDown={(e) => {
                  const startY = e.clientY;
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

      case 'console':
        return (
          <div className="flex-1 overflow-hidden">
            <AgentLogPanel />
          </div>
        );

      default:
        return null;
    }
  };

  return (
    <div className="flex flex-col h-full bg-fin-card border border-fin-border rounded-xl shadow-sm overflow-hidden">
      {/* Tab Header */}
      <div className="flex items-center justify-between px-2 py-1.5 border-b border-fin-border bg-fin-bg/50">
        <div className="flex items-center gap-1">
          <TabButton
            icon={<Bell size={14} />}
            active={activeTab === 'alerts'}
            onClick={handleAlertsTabClick}
            title="消息中心"
            badge={unreadCount}
          />
          <TabButton
            icon={<Activity size={14} />}
            active={activeTab === 'portfolio'}
            onClick={() => setActiveTab('portfolio')}
            title="资产组合"
          />
          <TabButton
            icon={<TrendingUp size={14} />}
            active={activeTab === 'chart'}
            onClick={() => setActiveTab('chart')}
            title="Market Chart"
          />
          <TabButton
            icon={<Terminal size={14} />}
            active={activeTab === 'console'}
            onClick={() => setActiveTab('console')}
            title="Console"
          />
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={refreshAll}
            className="p-1.5 hover:bg-fin-hover rounded text-fin-muted hover:text-fin-text transition-colors"
            title="Refresh"
          >
            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
          </button>
          <button
            onClick={onCollapse}
            className="p-1.5 hover:bg-fin-hover rounded text-fin-muted hover:text-fin-text transition-colors"
            title="Collapse"
          >
            <X size={12} />
          </button>
        </div>
      </div>

      {/* 上半区：Tab Content（可滚动） */}
      <div className="flex-1 min-h-0 overflow-hidden">
        {renderTabContent()}
      </div>

      {/* 下半区：MiniChat（仅在 Dashboard 视图显示，Chat 视图隐藏避免重复） */}
      {showMiniChat && (
        <div className="h-[45%] min-h-[180px] border-t border-fin-border flex flex-col">
          <MiniChat />
        </div>
      )}

      {/* Footer */}
      {lastUpdated && (
        <div className="text-[10px] text-fin-muted text-center py-1 border-t border-fin-border/50 shrink-0">
          上次更新: {lastUpdated.toLocaleTimeString()}
        </div>
      )}

      {/* Chart Maximize Modal */}
      {isChartMaximized && (
        <div className="fixed inset-0 z-[100] bg-black/80 backdrop-blur-sm flex items-center justify-center p-6">
          <div className="bg-fin-panel border border-fin-border rounded-xl w-full max-w-5xl h-[80vh] flex flex-col shadow-2xl animate-in fade-in zoom-in duration-200">
            <div className="flex items-center justify-between p-4 border-b border-fin-border/50">
              <div className="flex items-center gap-2">
                <TrendingUp className="text-fin-primary" size={20} />
                <span className="font-bold text-lg text-fin-text">Market Chart (Full View)</span>
              </div>
              <button
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
    </div>
  );
};
