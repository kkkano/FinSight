/**
 * Dashboard 页面 - 重构版
 *
 * 两栏布局：
 * - 左侧: Watchlist (220px 固定宽度)
 * - 右侧: 长滚动内容区（从上到下依次展示所有卡片）
 */
import { useEffect, useState } from 'react';
import { useDashboardData } from '../hooks/useDashboardData';
import { useDashboardStore } from '../store/dashboardStore';
import { Watchlist } from '../components/dashboard/Watchlist';
import { DashboardWidgets } from '../components/dashboard/DashboardWidgets';
import { Sun, Moon, RefreshCw } from 'lucide-react';
import { useStore } from '../store/useStore';

interface DashboardProps {
  /** 初始 symbol（来自 URL 参数） */
  initialSymbol?: string;
  /** 返回聊天视图的回调 */
  onBackToChat?: () => void;
}

export function Dashboard({ initialSymbol, onBackToChat }: DashboardProps) {
  // Dashboard Store
  const { activeAsset, isLoading, error, setActiveAsset } = useDashboardStore();

  // 主题
  const { theme, setTheme } = useStore();

  // 从 URL / props / localStorage（activeAsset）获取初始 symbol；兜底给 AAPL 保证首屏可加载
  const [currentSymbol, setCurrentSymbol] = useState<string>(
    () => initialSymbol || activeAsset?.symbol || 'AAPL'
  );

  // 当 parent 传入的 initialSymbol 变化时，同步更新 currentSymbol
  useEffect(() => {
    if (initialSymbol && initialSymbol !== currentSymbol) {
      setCurrentSymbol(initialSymbol);
      // 立即更新 activeAsset 的 symbol，避免 UI 显示旧值
      if (activeAsset && activeAsset.symbol !== initialSymbol) {
        setActiveAsset({ ...activeAsset, symbol: initialSymbol });
      }
    }
  }, [initialSymbol]);

  // 加载 Dashboard 数据
  const { refetch } = useDashboardData(currentSymbol);

  // currentSymbol 变化时同步 URL（单一来源同步，避免 activeAsset 反向覆盖）
  useEffect(() => {
    const url = new URL(window.location.href);
    const urlSymbol = url.searchParams.get('symbol');
    if (urlSymbol !== currentSymbol) {
      url.searchParams.set('symbol', currentSymbol);
      window.history.replaceState({}, '', url.toString());
    }
  }, [currentSymbol]);

  // 处理 Watchlist 项点击 - 切换到对应股票
  const handleSymbolChange = (symbol: string) => {
    setCurrentSymbol(symbol);
    // 立即更新 activeAsset 的 symbol，避免 Impact(旧值) 的问题
    setActiveAsset({
      symbol,
      display_name: symbol, // 临时显示 symbol，后端返回后会更新为完整名称
      type: activeAsset?.type || 'equity',
    });
    // 更新 URL
    const url = new URL(window.location.href);
    url.searchParams.set('symbol', symbol);
    window.history.pushState({}, '', url.toString());
  };

  // 手动刷新
  const handleRefresh = () => {
    refetch(currentSymbol);
  };

  return (
    <div className="flex-1 flex h-full overflow-hidden">
      {/* 左侧: Watchlist */}
      <aside className="w-[220px] shrink-0 border-r border-fin-border bg-fin-card flex flex-col">
        <Watchlist
          activeSymbol={activeAsset?.symbol || currentSymbol}
          onSymbolSelect={handleSymbolChange}
        />
      </aside>

      {/* 右侧: 主内容区 - 长滚动布局 */}
      <main className="flex-1 flex flex-col min-w-0 overflow-hidden bg-fin-bg">
        {/* Header - 固定在顶部 */}
        <header className="h-[52px] bg-fin-card border-b border-fin-border flex items-center justify-between px-5 shrink-0">
          <div className="flex items-center gap-3">
            {/* 返回按钮 */}
            {onBackToChat && (
              <button
                onClick={onBackToChat}
                className="px-3 py-1.5 rounded-lg border border-fin-border bg-fin-bg hover:bg-fin-hover transition-colors text-fin-text-secondary text-xs"
              >
                ← 返回对话
              </button>
            )}

            {/* 当前资产信息 */}
            {activeAsset && (
              <div className="flex items-center gap-2">
                <span className="text-lg font-bold text-fin-text">
                  {activeAsset.display_name}
                </span>
                <span className="text-[10px] text-fin-muted bg-fin-bg-secondary px-2 py-0.5 rounded">
                  {activeAsset.type.toUpperCase()}
                </span>
              </div>
            )}

            {/* 加载状态 */}
            {isLoading && (
              <span className="text-xs text-fin-muted animate-pulse">
                加载中...
              </span>
            )}
          </div>

          <div className="flex items-center gap-2">
            {/* 刷新按钮 */}
            <button
              onClick={handleRefresh}
              disabled={isLoading}
              className="p-2 rounded-lg border border-fin-border bg-fin-bg hover:bg-fin-hover transition-colors text-fin-text-secondary disabled:opacity-50"
              title="刷新数据"
            >
              <RefreshCw size={16} className={isLoading ? 'animate-spin' : ''} />
            </button>

            {/* 主题切换 */}
            <button
              onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
              className="p-2 rounded-lg border border-fin-border bg-fin-bg hover:bg-fin-hover transition-colors text-fin-text-secondary"
              title="切换主题"
            >
              {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
            </button>
          </div>
        </header>

        {/* 错误提示 */}
        {error && (
          <div className="mx-5 mt-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-600 text-sm flex items-center gap-2 shrink-0">
            <span className="font-medium">⚠ 加载失败：</span>
            <span className="truncate flex-1">{error}</span>
            <button
              onClick={handleRefresh}
              className="text-red-700 underline hover:no-underline whitespace-nowrap"
            >
              重试
            </button>
          </div>
        )}

        {/* 内容区 - 从上到下长滚动 */}
        <div className="flex-1 overflow-y-auto">
          <div className="p-5">
            <DashboardWidgets />
          </div>
        </div>
      </main>
    </div>
  );
}

export default Dashboard;
