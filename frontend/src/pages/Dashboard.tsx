/**
 * Dashboard v2 - TradingKey-style financial terminal layout.
 *
 * Structure:
 *   Watchlist (aside) | StockHeader
 *                      | MetricsBar
 *                      | DashboardTabs -> [Tab panels]
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowLeft, RefreshCw, Sun, Moon } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { useDashboardData } from '../hooks/useDashboardData';
import { useDashboardStore } from '../store/dashboardStore';
import { Watchlist } from '../components/dashboard/Watchlist';
import { StockHeader } from '../components/dashboard/StockHeader';
import { CNMarketNotice } from '../components/dashboard/CNMarketNotice';
import { MetricsBar } from '../components/dashboard/MetricsBar';
import { DashboardTabs } from '../components/dashboard/DashboardTabs';
import { DataSourceTrace } from '../components/dashboard/DataSourceTrace';
import { useStore } from '../store/useStore';
import { useToast } from '../components/ui';
import { useMarketQuotes } from '../hooks/useMarketQuotes';
import { getPredictionIdFromSearch } from '../components/chatChartIntent';
import { buildDashboardAskAiDraft } from '../utils/dashboardAskAi';
import { useMonitorLease } from '../hooks/useMonitorLease';
import { usePredictionOverlay } from '../hooks/usePredictionOverlay';
import { useChatHandoff } from '../hooks/useChatHandoff';
import { usePredictionGeneration } from '../hooks/usePredictionGeneration';
import { usePredictionEligibility } from '../hooks/usePredictionEligibility';
import { PredictionTrack } from '../components/dashboard/PredictionTrack';
import { MonitorActivityFeed } from '../components/dashboard/MonitorActivityFeed';

interface DashboardProps {
  initialSymbol?: string;
  onBackToChat?: () => void;
  onSymbolChange?: (symbol: string) => void;
}

const formatClock = (): string =>
  new Date().toLocaleTimeString('zh-CN', {
    hour12: false,
    timeZone: 'Asia/Shanghai',
  });

export function Dashboard({ initialSymbol, onBackToChat, onSymbolChange }: DashboardProps) {
  const { activeAsset, dashboardData, isLoading, error, setActiveAsset, watchlist } = useDashboardStore();
  const { theme, setTheme, authIdentity, sessionId } = useStore();
  const { quotes: marketQuotes } = useMarketQuotes();
  const { toast } = useToast();
  const [searchParams] = useSearchParams();
  const lastErrorRef = useRef<string | null>(null);
  const predictionId = getPredictionIdFromSearch(searchParams.toString());
  const handoffToChat = useChatHandoff();

  const [clock, setClock] = useState<string>(formatClock());
  const [currentSymbol, setCurrentSymbol] = useState<string>(
    () => initialSymbol || activeAsset?.symbol || watchlist[0]?.symbol || '',
  );
  const [predictionRefreshKey, setPredictionRefreshKey] = useState(0);
  useMonitorLease(currentSymbol);
  const authenticated = Boolean(authIdentity?.userId);
  const prediction = usePredictionOverlay(
    currentSymbol,
    predictionId,
    authenticated,
    predictionRefreshKey,
  );
  const predictionEligibility = usePredictionEligibility(currentSymbol);
  const predictionGeneration = usePredictionGeneration(currentSymbol, () => {
    setPredictionRefreshKey((value) => value + 1);
  });

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
    setPredictionRefreshKey((value) => value + 1);
  };

  const handleAskAi = () => {
    const symbol = (activeAsset?.symbol || currentSymbol).trim().toUpperCase();
    if (!symbol) return;
    if (!activeAsset || activeAsset.symbol !== symbol) {
      setActiveAsset({
        symbol,
        display_name: activeAsset?.display_name || symbol,
        type: activeAsset?.type || 'equity',
      });
    }
    handoffToChat({
      draft: buildDashboardAskAiDraft(symbol, searchParams.get('tab')),
      activeSymbol: symbol,
      sourceView: 'dashboard',
      sourceTab: searchParams.get('tab') || 'overview',
    });
  };

  const snapshot = dashboardData?.snapshot ?? {};
  const charts = dashboardData?.charts ?? {};
  const valuation = dashboardData?.valuation ?? null;
  const isTerminalStyle = theme === 'dark';

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
        <aside className="w-[220px] shrink-0 border-r border-fin-border bg-fin-card flex flex-col max-lg:w-full max-lg:h-[220px] max-lg:border-r-0 max-lg:border-b max-sm:h-[140px]">
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
    <div className="flex-1 min-h-0 flex flex-col overflow-hidden bg-t-bg text-t-text">
      {isTerminalStyle && (
        <div className="min-h-9 shrink-0 border-b border-t-divider bg-t-surface px-4 py-2 flex items-center justify-between gap-3 text-xs">
          <div className="flex min-w-0 items-center gap-3 text-t-text3">
            <span className="font-medium text-t-text2">行情工作区</span>
            <span className="max-sm:hidden">日线快照</span>
          </div>
          <div className="shrink-0 text-t-text3 tabular-nums">
            <span>{clock}</span>
            <span className="ml-2">UTC+8</span>
          </div>
        </div>
      )}

      <div className="flex-1 min-h-0 flex overflow-hidden max-lg:flex-col">
        <aside className="w-[220px] shrink-0 border-r border-t-divider bg-t-surface flex flex-col max-lg:w-full max-lg:h-[180px] max-lg:border-r-0 max-lg:border-b max-sm:h-[140px]">
          <Watchlist activeSymbol={activeAsset?.symbol || currentSymbol} onSymbolSelect={handleSymbolChange} />
        </aside>

        <main className="flex-1 min-w-0 min-h-0 flex flex-col overflow-y-auto bg-t-bg">
          <header className="min-h-[52px] border-b border-t-divider bg-t-surface flex items-center justify-between gap-3 px-6 py-2 shrink-0 max-lg:px-4">
            <div className="flex items-center gap-3 min-w-0">
              {onBackToChat && (
                <button
                  type="button"
                  data-testid="dashboard-back-chat"
                  onClick={onBackToChat}
                  className="inline-flex min-h-9 items-center gap-1.5 px-2 rounded-md text-sm shrink-0 text-t-text2 transition-colors hover:bg-t-hover hover:text-t-text"
                >
                  <ArrowLeft size={15} /> 对话
                </button>
              )}

              {isLoading && <span className="text-xs text-fin-muted animate-pulse shrink-0">加载中...</span>}
            </div>

            <div className="flex items-center gap-2 shrink-0">
              <DataSourceTrace meta={dashboardData?.meta} />

              <button
                type="button"
                onClick={handleRefresh}
                disabled={isLoading}
                className="p-2 rounded-md text-t-text2 transition-colors hover:bg-t-hover hover:text-t-text disabled:opacity-50"
                title="刷新数据"
                aria-label="刷新数据"
              >
                <RefreshCw size={16} className={isLoading ? 'animate-spin' : ''} />
              </button>

              <button
                type="button"
                onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
                className="p-2 rounded-md text-t-text2 transition-colors hover:bg-t-hover hover:text-t-text"
                title="切换主题"
                aria-label="切换主题"
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

          <CNMarketNotice ticker={activeAsset?.symbol || currentSymbol} />

          <MetricsBar
            valuation={valuation}
            snapshot={snapshot}
            ticker={activeAsset?.symbol || currentSymbol}
            loading={isLoading && !dashboardData}
          />

          <PredictionTrack
            authenticated={authenticated}
            eligibility={predictionEligibility}
            loadState={prediction}
            generationPhase={predictionGeneration.phase}
            generationRun={predictionGeneration.run}
            generationFailure={predictionGeneration.failure}
            isGenerating={predictionGeneration.isGenerating}
            onGenerate={() => { void predictionGeneration.generate(); }}
            onAsk={handleAskAi}
          />

          <MonitorActivityFeed
            sessionId={sessionId}
            symbol={activeAsset?.symbol || currentSymbol}
          />

          <DashboardTabs predictionOverlay={prediction.overlay} />

          {isTerminalStyle && (
            <div className="h-9 shrink-0 border-t border-t-divider bg-t-surface overflow-hidden flex items-center">
              <div className="flex w-max items-center gap-8 px-4 text-xs tabular-nums text-t-text2" style={{ animation: 'finsight-marquee 36s linear infinite' }}>
                {[...tickerTapeItems, ...tickerTapeItems].map((item, idx) => (
                  <span key={`${item.key}-${idx}`} className="whitespace-nowrap">
                    <span className="text-t-text3 mr-1">{item.label}</span>
                    <span className={item.up ? 'text-t-up' : 'text-t-down'}>{item.text.replace(`${item.label} `, '')}</span>
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
