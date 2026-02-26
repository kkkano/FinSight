/**
 * Dashboard v2 - TradingKey-style financial terminal layout.
 *
 * Structure:
 *   Watchlist (aside) | StockHeader
 *                      | MetricsBar
 *                      | DashboardTabs -> [Tab panels]
 */
import { useEffect, useRef, useState } from 'react';
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

interface DashboardProps {
  initialSymbol?: string;
  onBackToChat?: () => void;
  onSymbolChange?: (symbol: string) => void;
  onGoWorkbench?: (symbol: string) => void;
}

export function Dashboard({ initialSymbol, onBackToChat, onSymbolChange, onGoWorkbench }: DashboardProps) {
  const { activeAsset, dashboardData, isLoading, error, setActiveAsset } = useDashboardStore();
  const { theme, setTheme } = useStore();
  const { toast } = useToast();
  const lastErrorRef = useRef<string | null>(null);

  const [currentSymbol, setCurrentSymbol] = useState<string>(
    () => initialSymbol || activeAsset?.symbol || '',
  );

  useEffect(() => {
    if (!initialSymbol || initialSymbol === currentSymbol) return;

    setCurrentSymbol(initialSymbol);
    if (activeAsset && activeAsset.symbol !== initialSymbol) {
      setActiveAsset({ ...activeAsset, symbol: initialSymbol });
    }
  }, [activeAsset, currentSymbol, initialSymbol, setActiveAsset]);

  const { refetch } = useDashboardData(currentSymbol);
  // AI Insights: parallel fetch alongside dashboard data
  const { refetch: refetchInsights } = useDashboardInsights(currentSymbol);

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

  // Derived data for sub-components
  const snapshot = dashboardData?.snapshot ?? {};
  const charts = dashboardData?.charts ?? {};
  const valuation = dashboardData?.valuation ?? null;

  // No symbol selected — show onboarding prompt instead of loading empty data
  if (!currentSymbol) {
    return (
      <div className="flex-1 min-h-0 flex overflow-hidden max-lg:flex-col">
        <aside className="w-[220px] shrink-0 border-r border-fin-border bg-fin-card flex flex-col max-lg:w-full max-lg:h-[220px] max-lg:border-r-0 max-lg:border-b">
          <Watchlist activeSymbol="" onSymbolSelect={handleSymbolChange} />
        </aside>
        <main className="flex-1 min-w-0 min-h-0 flex flex-col items-center justify-center bg-fin-bg">
          <div className="text-center max-w-md px-6">
            <div className="text-4xl mb-4">📊</div>
            <h2 className="text-lg font-semibold text-fin-text mb-2">选择一只股票开始分析</h2>
            <p className="text-sm text-fin-muted mb-6">
              在左侧自选列表中点击一只股票，或在上方搜索栏输入代码（如 AAPL、TSLA、GOOGL）
            </p>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="flex-1 min-h-0 flex overflow-hidden max-lg:flex-col">
      <aside className="w-[220px] shrink-0 border-r border-fin-border bg-fin-card flex flex-col max-lg:w-full max-lg:h-[220px] max-lg:border-r-0 max-lg:border-b">
        <Watchlist activeSymbol={activeAsset?.symbol || currentSymbol} onSymbolSelect={handleSymbolChange} />
      </aside>

      <main className="flex-1 min-w-0 min-h-0 flex flex-col overflow-hidden bg-fin-bg">
        {/* Navigation header bar */}
        <header className="h-[52px] bg-fin-card border-b border-fin-border flex items-center justify-between px-5 shrink-0 max-lg:px-3">
          <div className="flex items-center gap-3 min-w-0">
            {onBackToChat && (
              <div className="flex items-center gap-2 shrink-0">
                <button
                  type="button"
                  data-testid="dashboard-back-chat"
                  onClick={onBackToChat}
                  className="px-3 py-1.5 rounded-lg border border-fin-border bg-fin-bg hover:bg-fin-hover transition-colors text-fin-text-secondary text-xs"
                >
                  返回对话
                </button>
                {onGoWorkbench && (
                  <button
                    type="button"
                    data-testid="dashboard-go-workbench"
                    onClick={() => onGoWorkbench(activeAsset?.symbol || currentSymbol)}
                    className="px-3 py-1.5 rounded-lg border border-fin-primary/40 bg-fin-primary/10 hover:bg-fin-primary/20 transition-colors text-fin-primary text-xs"
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
              className="p-2 rounded-lg border border-fin-border bg-fin-bg hover:bg-fin-hover transition-colors text-fin-text-secondary disabled:opacity-50"
              title="刷新数据"
            >
              <RefreshCw size={16} className={isLoading ? 'animate-spin' : ''} />
            </button>

            <button
              type="button"
              onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
              className="p-2 rounded-lg border border-fin-border bg-fin-bg hover:bg-fin-hover transition-colors text-fin-text-secondary"
              title="切换主题"
            >
              {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
            </button>
          </div>
        </header>

        {/* Error banner */}
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

        {/* StockHeader: symbol info + price + action buttons */}
        <StockHeader
          ticker={activeAsset?.symbol || currentSymbol}
          displayName={activeAsset?.display_name || currentSymbol}
          assetType={activeAsset?.type || 'equity'}
          snapshot={snapshot}
          charts={charts}
          valuation={valuation}
          loading={isLoading && !dashboardData}
        />

        {/* MetricsBar: key valuation indicators */}
        <MetricsBar
          valuation={valuation}
          snapshot={snapshot}
          loading={isLoading && !dashboardData}
        />

        {/* Tabs + Tab panels */}
        <DashboardTabs />
      </main>
    </div>
  );
}

export default Dashboard;
