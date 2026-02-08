import { useEffect, useState } from 'react';
import { RefreshCw, Sun, Moon } from 'lucide-react';
import { useDashboardData } from '../hooks/useDashboardData';
import { useDashboardStore } from '../store/dashboardStore';
import { Watchlist } from '../components/dashboard/Watchlist';
import { DashboardWidgets } from '../components/dashboard/DashboardWidgets';
import { useStore } from '../store/useStore';

interface DashboardProps {
  initialSymbol?: string;
  onBackToChat?: () => void;
  onSymbolChange?: (symbol: string) => void;
  onGoWorkbench?: (symbol: string) => void;
}

export function Dashboard({ initialSymbol, onBackToChat, onSymbolChange, onGoWorkbench }: DashboardProps) {
  const { activeAsset, isLoading, error, setActiveAsset } = useDashboardStore();
  const { theme, setTheme } = useStore();

  const [currentSymbol, setCurrentSymbol] = useState<string>(
    () => initialSymbol || activeAsset?.symbol || 'AAPL',
  );

  useEffect(() => {
    if (!initialSymbol || initialSymbol === currentSymbol) return;

    setCurrentSymbol(initialSymbol);
    if (activeAsset && activeAsset.symbol !== initialSymbol) {
      setActiveAsset({ ...activeAsset, symbol: initialSymbol });
    }
  }, [activeAsset, currentSymbol, initialSymbol, setActiveAsset]);

  const { refetch } = useDashboardData(currentSymbol);

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
  };

  return (
    <div className="flex-1 min-h-0 flex overflow-hidden max-lg:flex-col">
      <aside className="w-[220px] shrink-0 border-r border-fin-border bg-fin-card flex flex-col max-lg:w-full max-lg:h-[220px] max-lg:border-r-0 max-lg:border-b">
        <Watchlist activeSymbol={activeAsset?.symbol || currentSymbol} onSymbolSelect={handleSymbolChange} />
      </aside>

      <main className="flex-1 min-w-0 min-h-0 flex flex-col overflow-hidden bg-fin-bg">
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

            {activeAsset && (
              <div className="flex items-center gap-2 min-w-0">
                <span className="text-lg font-bold text-fin-text truncate">{activeAsset.display_name}</span>
                <span className="text-2xs text-fin-muted bg-fin-bg-secondary px-2 py-0.5 rounded shrink-0">
                  {activeAsset.type.toUpperCase()}
                </span>
              </div>
            )}

            {isLoading && <span className="text-xs text-fin-muted animate-pulse shrink-0">加载中...</span>}
          </div>

          <div className="flex items-center gap-2 shrink-0">
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

        {error && (
          <div className="mx-5 mt-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-600 text-sm flex items-center gap-2 shrink-0 max-lg:mx-3">
            <span className="font-medium">加载失败：</span>
            <span className="truncate flex-1">{error}</span>
            <button
              type="button"
              onClick={handleRefresh}
              className="text-red-700 underline hover:no-underline whitespace-nowrap"
            >
              重试
            </button>
          </div>
        )}

        <div className="flex-1 min-h-0 overflow-y-auto">
          <div className="p-5 max-lg:p-3">
            <DashboardWidgets />
          </div>
        </div>
      </main>
    </div>
  );
}

export default Dashboard;
