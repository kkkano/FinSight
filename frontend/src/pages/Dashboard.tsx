/**
 * Dashboard v2 - TradingKey-style financial terminal layout.
 *
 * Structure:
 *   Watchlist (aside) | StockHeader
 *                      | MetricsBar
 *                      | DashboardTabs -> [Tab panels]
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { RefreshCw, Sun, Moon } from 'lucide-react';
import { useDashboardData } from '../hooks/useDashboardData';
import { useDashboardInsights } from '../hooks/useDashboardInsights';
import { useDashboardStore } from '../store/dashboardStore';
import { Watchlist } from '../components/dashboard/Watchlist';
import { StockHeader } from '../components/dashboard/StockHeader';
import { MetricsBar } from '../components/dashboard/MetricsBar';
import { DashboardTabs } from '../components/dashboard/DashboardTabs';
import { DataSourceTrace } from '../components/dashboard/DataSourceTrace';
import { useStore } from '../store/useStore';
import { useToast } from '../components/ui';
import { useMarketQuotes } from '../hooks/useMarketQuotes';

interface DashboardProps {
  initialSymbol?: string;
  onBackToChat?: () => void;
  onSymbolChange?: (symbol: string) => void;
  onGoWorkbench?: (symbol: string) => void;
}

const formatClock = (): string =>
  new Date().toLocaleTimeString('zh-CN', {
    hour12: false,
    timeZone: 'Asia/Shanghai',
  });

export function Dashboard({ initialSymbol, onBackToChat, onSymbolChange, onGoWorkbench }: DashboardProps) {
  const { activeAsset, dashboardData, isLoading, error, setActiveAsset, watchlist } = useDashboardStore();
  const { theme, setTheme, entryMode, authIdentity } = useStore();
  const { quotes: marketQuotes } = useMarketQuotes();
  const { toast } = useToast();
  const lastErrorRef = useRef<string | null>(null);

  const [clock, setClock] = useState<string>(formatClock());
  const [currentSymbol, setCurrentSymbol] = useState<string>(
    () => initialSymbol || activeAsset?.symbol || watchlist[0]?.symbol || '',
  );

  useEffect(() => {
    const timer = window.setInterval(() => setClock(formatClock()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!initialSymbol || initialSymbol === currentSymbol) return;

    setCurrentSymbol(initialSymbol);
    if (activeAsset && activeAsset.symbol !== initialSymbol) {
      setActiveAsset({ ...activeAsset, symbol: initialSymbol });
    }
  }, [activeAsset, currentSymbol, initialSymbol, setActiveAsset]);

  const { refetch } = useDashboardData(currentSymbol);
  const { refetch: refetchInsights } = useDashboardInsights(currentSymbol);

  // Expose insights refetch to store so child tabs can trigger refresh
  const setInsightsRefetch = useDashboardStore((s) => s.setInsightsRefetch);
  useEffect(() => {
    setInsightsRefetch(() => refetchInsights(currentSymbol, { force: true }));
    return () => setInsightsRefetch(null);
  }, [currentSymbol, refetchInsights, setInsightsRefetch]);

  useEffect(() => {
    if (!error) {
      lastErrorRef.current = null;
      return;
    }
    if (lastErrorRef.current === error) {
      return;
    }
    lastErrorRef.current = error;
    toast({
      type: 'error',
      title: '加载失败',
      message: error,
    });
  }, [error, toast]);

  const handleSymbolChange = (symbol: string) => {
    setCurrentSymbol(symbol);
    setActiveAsset({
      symbol,
      display_name: symbol,
      type: activeAsset?.type || 'equity',
    });
    onSymbolChange?.(symbol);
  };

  const handleRefresh = () => {
    refetch(currentSymbol);
    refetchInsights(currentSymbol, { force: true });
  };

  const snapshot = dashboardData?.snapshot ?? {};
  const charts = dashboardData?.charts ?? {};
  const valuation = dashboardData?.valuation ?? null;

  const isTerminalStyle = theme === 'dark';
  const sessionText = authIdentity?.email || (entryMode === 'anonymous' ? 'ANON' : 'GUEST');

  const tickerTapeItems = useMemo(() => {
    const list = marketQuotes
      .filter((item) => typeof item.price === 'number')
      .map((item) => {
        const pct = typeof item.changePct === 'number' ? item.changePct : 0;
        const sign = pct >= 0 ? '+' : '';
        return {
          key: item.label,
          label: item.label,
          text: `${item.label} ${typeof item.price === 'number' ? item.price.toFixed(2) : '--'} ${sign}${pct.toFixed(2)}%`,
          up: pct >= 0,
        };
      });

    if (list.length > 0) return list;

    return [
      { key: 'AAPL', label: 'AAPL', text: 'AAPL --', up: true },
      { key: 'NVDA', label: 'NVDA', text: 'NVDA --', up: true },
      { key: 'TSLA', label: 'TSLA', text: 'TSLA --', up: false },
      { key: 'MSFT', label: 'MSFT', text: 'MSFT --', up: true },
    ];
  }, [marketQuotes]);

  if (!currentSymbol) {
    return (
      <div className="flex-1 min-h-0 flex overflow-hidden max-lg:flex-col">
        <aside className="w-[220px] shrink-0 border-r border-fin-border bg-fin-card flex flex-col max-lg:w-full max-lg:h-[220px] max-lg:border-r-0 max-lg:border-b">
          <Watchlist activeSymbol="" onSymbolSelect={handleSymbolChange} />
        </aside>
        <main className="flex-1 min-w-0 min-h-0 flex flex-col items-center justify-center bg-fin-bg">
          <div className="text-center max-w-md px-6">
            <div className="text-4xl mb-4">📳</div>
            <h2 className="text-lg font-semibold text-fin-text mb-2">选择一只股票开始分析</h2>
            <p className="text-sm text-fin-muted mb-6">
              在左侧自选列表中点击一只股票，或在上方搜索栏输入代码（如 AAPL、TSLA、GOOGL）。
            </p>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className={[
      'flex-1 min-h-0 flex flex-col overflow-hidden',
      isTerminalStyle ? 'bg-[#0a0e17] text-slate-100' : 'bg-fin-bg text-fin-text',
    ].join(' ')}>
      {isTerminalStyle && (
        <div className="h-9 shrink-0 border-b border-[#1e2a3a] bg-[#111827] px-4 flex items-center justify-between text-[11px] font-mono">
          <div className="flex items-center gap-5 text-slate-400">
            <span className="text-[#ff8c00] font-semibold tracking-wide">FINSIGHT TERMINAL</span>
            <span>SESSION: <span className="text-slate-200">{sessionText}</span></span>
            <span>
              MARKET:
              <span className="ml-1 text-emerald-400">OPEN</span>
            </span>
          </div>
          <div className="text-slate-400">
            <span className="text-[#ff8c00] font-semibold">{clock}</span>
            <span className="ml-2">UTC+8</span>
          </div>
        </div>
      )}

      <div className="flex-1 min-h-0 flex overflow-hidden max-lg:flex-col">
        <aside
          className={[
            'w-[220px] shrink-0 border-r flex flex-col max-lg:w-full max-lg:h-[220px] max-lg:border-r-0 max-lg:border-b',
            isTerminalStyle ? 'border-[#1e2a3a] bg-[#111827]' : 'border-fin-border bg-fin-card',
          ].join(' ')}
        >
          <Watchlist activeSymbol={activeAsset?.symbol || currentSymbol} onSymbolSelect={handleSymbolChange} />
        </aside>

        <main className={[
          'flex-1 min-w-0 min-h-0 flex flex-col overflow-hidden',
          isTerminalStyle ? 'bg-[#0a0e17]' : 'bg-fin-bg',
        ].join(' ')}>
          <header
            className={[
              'h-[52px] border-b flex items-center justify-between px-5 shrink-0 max-lg:px-3',
              isTerminalStyle ? 'bg-[#111827] border-[#1e2a3a]' : 'bg-fin-card border-fin-border',
            ].join(' ')}
          >
            <div className="flex items-center gap-3 min-w-0">
              {onBackToChat && (
                <div className="flex items-center gap-2 shrink-0">
                  <button
                    type="button"
                    data-testid="dashboard-back-chat"
                    onClick={onBackToChat}
                    className={[
                      'px-3 py-1.5 rounded-lg border transition-colors text-xs',
                      isTerminalStyle
                        ? 'border-[#2b3a52] bg-[#0a0e17] text-slate-300 hover:border-[#ff8c00] hover:text-[#ff8c00]'
                        : 'border-fin-border bg-fin-bg text-fin-text-secondary hover:bg-fin-hover',
                    ].join(' ')}
                  >
                    返回对话
                  </button>
                  {onGoWorkbench && (
                    <button
                      type="button"
                      data-testid="dashboard-go-workbench"
                      onClick={() => onGoWorkbench(activeAsset?.symbol || currentSymbol)}
                      className={[
                        'px-3 py-1.5 rounded-lg border transition-colors text-xs',
                        isTerminalStyle
                          ? 'border-[#ff8c00]/40 bg-[#ff8c00]/15 text-[#ff8c00] hover:bg-[#ff8c00]/25'
                          : 'border-fin-primary/40 bg-fin-primary/10 text-fin-primary hover:bg-fin-primary/20',
                      ].join(' ')}
                    >
                      去工作台
                    </button>
                  )}
                </div>
              )}

              {isLoading && <span className="text-xs text-fin-muted animate-pulse shrink-0">加载中...</span>}
            </div>

            <div className="flex items-center gap-2 shrink-0">
              <DataSourceTrace meta={dashboardData?.meta} />

              <button
                type="button"
                onClick={handleRefresh}
                disabled={isLoading}
                className={[
                  'p-2 rounded-lg border transition-colors disabled:opacity-50',
                  isTerminalStyle
                    ? 'border-[#2b3a52] bg-[#0a0e17] text-slate-300 hover:border-[#ff8c00] hover:text-[#ff8c00]'
                    : 'border-fin-border bg-fin-bg text-fin-text-secondary hover:bg-fin-hover',
                ].join(' ')}
                title="刷新数据"
              >
                <RefreshCw size={16} className={isLoading ? 'animate-spin' : ''} />
              </button>

              <button
                type="button"
                onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
                className={[
                  'p-2 rounded-lg border transition-colors',
                  isTerminalStyle
                    ? 'border-[#2b3a52] bg-[#0a0e17] text-slate-300 hover:border-[#ff8c00] hover:text-[#ff8c00]'
                    : 'border-fin-border bg-fin-bg text-fin-text-secondary hover:bg-fin-hover',
                ].join(' ')}
                title="切换主题"
              >
                {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
              </button>
            </div>
          </header>

          {error && (
            <div className="mx-5 mt-4 p-2 bg-fin-danger/10 border border-fin-danger/30 rounded-lg text-fin-danger text-sm flex items-center gap-2 shrink-0 max-lg:mx-3">
              <span className="font-medium">加载失败:</span>
              <span className="truncate flex-1">{error}</span>
              <button
                type="button"
                onClick={handleRefresh}
                className="text-fin-danger font-medium underline hover:no-underline whitespace-nowrap"
              >
                重试
              </button>
            </div>
          )}

          <StockHeader
            ticker={activeAsset?.symbol || currentSymbol}
            displayName={activeAsset?.display_name || currentSymbol}
            assetType={activeAsset?.type || 'equity'}
            snapshot={snapshot}
            charts={charts}
            valuation={valuation}
            loading={isLoading && !dashboardData}
          />

          <MetricsBar
            valuation={valuation}
            snapshot={snapshot}
            loading={isLoading && !dashboardData}
          />

          <DashboardTabs />

          {isTerminalStyle && (
            <div className="h-8 shrink-0 border-t border-[#1e2a3a] bg-[#111827] overflow-hidden flex items-center">
              <div className="flex w-max items-center gap-8 px-4 text-[11px] font-mono text-slate-300" style={{ animation: 'finsight-marquee 36s linear infinite' }}>
                {[...tickerTapeItems, ...tickerTapeItems].map((item, idx) => (
                  <span key={`${item.key}-${idx}`} className="whitespace-nowrap">
                    <span className="text-slate-400 mr-1">{item.label}</span>
                    <span className={item.up ? 'text-emerald-400' : 'text-red-400'}>{item.text.replace(`${item.label} `, '')}</span>
                  </span>
                ))}
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

export default Dashboard;
