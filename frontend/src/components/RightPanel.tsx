import { useEffect, useMemo, useState } from 'react';
import { apiClient } from '../api/client';
import { useStore } from '../store/useStore';
import { StockChart } from './StockChart';
import { Activity, Bell, Bookmark, RefreshCw, TrendingUp, Plus, Minus, X, ChevronDown, ChevronUp, Maximize2 } from 'lucide-react';

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

const formatPrice = (value?: number | null) => {
  if (value === undefined || value === null || Number.isNaN(value)) return '--';
  return `$${value.toFixed(2)}`;
};

const formatChangePct = (value?: number | null) => {
  if (value === undefined || value === null || Number.isNaN(value)) return '--';
  const sign = value >= 0 ? '+' : '';
  return `${sign}${value.toFixed(2)}%`;
};

// Collapsible Widget
const Widget: React.FC<{
  title: string;
  icon?: React.ReactNode;
  action?: React.ReactNode;
  defaultOpen?: boolean;
  children: React.ReactNode;
}> = ({ title, icon, action, defaultOpen = true, children }) => {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  return (
    <section className="bg-fin-card border border-fin-border rounded-xl shadow-sm flex flex-col">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center justify-between p-3 hover:bg-fin-hover/50 transition-colors rounded-t-xl"
      >
        <div className="flex items-center gap-2 text-xs font-semibold text-fin-text-secondary uppercase tracking-wider">
          {icon}
          {title}
        </div>
        <div className="flex items-center gap-2">
          {action}
          {isOpen ? <ChevronUp size={14} className="text-fin-muted" /> : <ChevronDown size={14} className="text-fin-muted" />}
        </div>
      </button>
      {isOpen && <div className="px-4 pb-4">{children}</div>}
    </section>
  );
};

export const RightPanel: React.FC<{ onCollapse: () => void }> = ({ onCollapse }) => {
  const { currentTicker, subscriptionEmail } = useStore();
  const [marketQuotes, setMarketQuotes] = useState<Quote[]>([]);
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);
  const [watchlistInput, setWatchlistInput] = useState('');
  const [alerts, setAlerts] = useState<any[]>([]);
  const [langgraph, setLanggraph] = useState<any>(null);
  const [orchestrator, setOrchestrator] = useState<any>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [loading, setLoading] = useState(false);
  const [chartHeight, setChartHeight] = useState(250);
  const [isChartMaximized, setIsChartMaximized] = useState(false);

  // 监听全屏状态下的 ESC 用于退出
  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setIsChartMaximized(false);
    };
    window.addEventListener('keydown', handleEsc);
    return () => window.removeEventListener('keydown', handleEsc);
  }, []);

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

  const loadDiagnostics = async () => {
    try {
      const [lg, oc] = await Promise.all([
        apiClient.diagnosticsLanggraph(),
        apiClient.diagnosticsOrchestrator(),
      ]);
      // 正确读取嵌套结构
      setLanggraph(lg);
      setOrchestrator(oc);
    } catch (error) {
      setLanggraph(null);
      setOrchestrator(null);
    }
  };

  const refreshAll = async () => {
    setLoading(true);
    await Promise.all([loadMarketQuotes(), loadWatchlist(), loadAlerts(), loadDiagnostics()]);
    setLastUpdated(new Date());
    setLoading(false);
  };

  useEffect(() => {
    refreshAll();
    const timer = setInterval(refreshAll, 60000);
    return () => clearInterval(timer);
  }, [subscriptionEmail]);

  const handleAddWatchlist = async () => {
    const ticker = watchlistInput.trim().toUpperCase();
    if (!ticker) return;
    await apiClient.addWatchlist({ user_id: DEFAULT_USER_ID, ticker });
    setWatchlistInput('');
    await loadWatchlist();
  };

  const handleRemoveWatchlist = async (ticker: string) => {
    await apiClient.removeWatchlist({ user_id: DEFAULT_USER_ID, ticker });
    await loadWatchlist();
  };

  const portfolioSummary = useMemo(() => {
    if (watchlist.length === 0) return null;
    const basePer = 10000;
    const totalValue = basePer * watchlist.length;
    const changePcts = watchlist
      .map((item) => item.changePct)
      .filter((value): value is number => typeof value === 'number');
    const avgChange = changePcts.length
      ? changePcts.reduce((sum, v) => sum + v, 0) / changePcts.length
      : 0;
    const dayChange = (totalValue * avgChange) / 100;
    const topMover = [...watchlist]
      .filter((item) => typeof item.changePct === 'number')
      .sort((a, b) => Math.abs((b.changePct || 0)) - Math.abs((a.changePct || 0)))[0];
    return { totalValue, dayChange, avgChange, topMover };
  }, [watchlist]);

  // 从真实后端数据提取 Agent 状态
  const agentInfo = langgraph?.data?.agent_info;
  const orchestratorStats = orchestrator?.data?.orchestrator_stats;
  const sourceStats = orchestrator?.data?.by_source?.stock_price || [];

  // 计算总请求数 (从所有数据源累加)
  const totalCalls = sourceStats.reduce((sum: number, s: any) => sum + (s.total_calls || 0), 0);
  const totalSuccesses = sourceStats.reduce((sum: number, s: any) => sum + (s.total_successes || 0), 0);
  const cacheHits = orchestratorStats?.cache_hits ?? orchestrator?.data?.cache_hits ?? 0;
  const fallbackCount = orchestratorStats?.fallback_count ?? orchestrator?.data?.fallback_count ?? 0;

  return (
    <div className="flex flex-col gap-3 h-full overflow-y-auto pr-1">
      {/* Header Actions */}
      <div className="flex items-center justify-between pb-2">
        <span className="text-xs font-bold text-fin-text-secondary uppercase">Context Awareness</span>
        <div className="flex gap-2">
          <button onClick={refreshAll} className="p-1 hover:bg-fin-hover rounded text-fin-muted" title="Refresh">
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          </button>
          <button onClick={onCollapse} className="p-1 hover:bg-fin-hover rounded text-fin-muted" title="Collapse">
            <X size={14} />
          </button>
        </div>
      </div>

      {/* 消息中心 - 可收起 */}
      <Widget title="消息中心" icon={<Bell size={14} />} action={<span className="text-[10px] text-fin-muted bg-fin-bg px-1.5 rounded">{alerts.length} 条</span>}>
        <div className="flex flex-col gap-2">
          {alerts.slice(0, 5).map((item, idx) => (
            <div key={idx} className="flex justify-between items-center border-b border-fin-border/50 pb-2 last:border-0">
              <div className="flex gap-2 items-center">
                <span className="text-fin-primary text-sm">🚀</span>
                <div>
                  <div className="text-xs font-semibold text-fin-text">{item.ticker} 触发提醒</div>
                  <div className="text-[10px] text-fin-text-secondary">{(item.alert_types || []).join(', ')}</div>
                </div>
              </div>
              <div className="text-[10px] text-fin-muted">触发 0 次</div>
            </div>
          ))}
          {alerts.length === 0 && <div className="text-xs text-fin-muted py-2">暂无订阅提醒</div>}
          <button className="w-full py-1.5 border border-dashed border-fin-border rounded text-xs text-fin-text-secondary hover:text-fin-primary hover:border-fin-primary transition-colors">
            + 管理订阅规则
          </button>
        </div>
      </Widget>

      {/* 资产组合 - 可收起 */}
      <Widget title="资产组合快照" icon={<Activity size={14} />}>
        {portfolioSummary ? (
          <div className="space-y-1">
            <div className="text-xl font-bold text-fin-text">${portfolioSummary.totalValue.toLocaleString()}</div>
            <div className={`text-sm font-medium ${portfolioSummary.dayChange >= 0 ? 'text-fin-success' : 'text-fin-danger'}`}>
              {portfolioSummary.dayChange >= 0 ? '+' : ''}{portfolioSummary.dayChange.toFixed(0)} ({formatChangePct(portfolioSummary.avgChange)})
            </div>
            <div className="text-[10px] text-fin-muted mt-2">模拟持仓，仅用于展示</div>
          </div>
        ) : (
          <div className="text-xs text-fin-muted">添加 Watchlist 后生成组合摘要</div>
        )}
      </Widget>

      {/* Market Chart - 可收起且可拉伸 */}
      <Widget
        title="Market Chart"
        icon={<TrendingUp size={14} />}
        action={
          <button
            onClick={() => setIsChartMaximized(true)}
            className="p-1 hover:bg-fin-hover rounded text-fin-muted hover:text-fin-primary transition-colors"
            title="全屏查看图表"
          >
            <Maximize2 size={12} />
          </button>
        }
      >
        <div className="relative">
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
      </Widget>

      {/* Agent 运行状态 - 真实数据 */}
      <Widget title="Agent 运行状态" icon={<Activity size={14} />}>
        <div className="space-y-2 text-xs">
          {/* Provider/Model Info */}
          <div className="flex items-center justify-between pb-2 border-b border-fin-border/50">
            <span className="text-fin-muted">Provider</span>
            <span className="text-fin-text font-medium">{agentInfo?.provider || 'Unknown'}</span>
          </div>
          <div className="flex items-center justify-between pb-2 border-b border-fin-border/50">
            <span className="text-fin-muted">Model</span>
            <span className="text-fin-text font-medium">{agentInfo?.model || 'Unknown'}</span>
          </div>
          <div className="flex items-center justify-between pb-2 border-b border-fin-border/50">
            <span className="text-fin-muted">Tools</span>
            <span className="text-fin-text font-medium">{agentInfo?.tools_count || 0} 个</span>
          </div>
          {/* Stats */}
          <div className="flex items-center justify-between">
            <span className="text-fin-muted">总请求</span>
            <span className="text-fin-text">{totalCalls}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-fin-muted">成功</span>
            <span className="text-fin-success">{totalSuccesses}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-fin-muted">缓存命中</span>
            <span className="text-fin-text">{cacheHits}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-fin-muted">回退次数</span>
            <span className="text-fin-warning">{fallbackCount}</span>
          </div>
          {/* Data Sources */}
          {sourceStats.length > 0 && (
            <div className="pt-2 border-t border-fin-border/50">
              <div className="text-[10px] text-fin-muted mb-1 uppercase">数据源状态</div>
              <div className="space-y-1">
                {sourceStats.slice(0, 4).map((src: any) => (
                  <div key={src.name} className="flex items-center justify-between text-[10px]">
                    <div className="flex items-center gap-1">
                      <span className={`w-1.5 h-1.5 rounded-full ${src.circuit_state === 'CLOSED' ? 'bg-fin-success' : 'bg-fin-danger'}`} />
                      <span className="text-fin-text">{src.name}</span>
                    </div>
                    <span className="text-fin-muted">{src.total_calls || 0} calls</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </Widget>

      {/* Footer */}
      {lastUpdated && (
        <div className="text-[10px] text-fin-muted text-center py-1">
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
