import { useEffect, useState, useMemo, useRef, useCallback } from 'react';
import { ChatList } from './components/ChatList';
import Sidebar from './components/Sidebar';
import { ChatInput } from './components/ChatInput';
import { SettingsModal } from './components/SettingsModal';
import { SubscribeModal } from './components/SubscribeModal';
import { Sun, Moon, ChevronLeft } from 'lucide-react';
import { useStore } from './store/useStore';
import { apiClient } from './api/client';
import { RightPanel } from './components/RightPanel';
import { Dashboard } from './pages/Dashboard';

// 市场指数配置
const MARKET_INDICES = [
  { label: 'S&P 500', ticker: '^GSPC', flag: '🇺🇸' },
  { label: '沪深300', ticker: '000300.SS', flag: '🇨🇳' },
  { label: '黄金', ticker: 'GC=F', flag: '🌕' },
  { label: 'BTC', ticker: 'BTC-USD', flag: '₿' },
];

type MarketQuote = {
  label: string;
  flag: string;
  price?: number;
  changePct?: number;
  loading?: boolean;
};

// 视图类型
type ViewType = 'chat' | 'dashboard';

// 右侧面板宽度约束
const DEFAULT_PANEL_WIDTH = 380;
const MIN_PANEL_WIDTH = 280;
const MAX_PANEL_WIDTH = 600;
const PANEL_WIDTH_STORAGE_KEY = 'finsight_right_panel_width';

function App() {
  // 读取 URL 参数判断初始视图
  const initialView = useMemo<ViewType>(() => {
    const urlParams = new URLSearchParams(window.location.search);
    const dashboardSymbol = urlParams.get('symbol');
    return dashboardSymbol ? 'dashboard' : 'chat';
  }, []);

  const initialSymbol = useMemo(() => {
    const urlParams = new URLSearchParams(window.location.search);
    return urlParams.get('symbol');
  }, []);

  // 视图状态
  const [view, setView] = useState<ViewType>(initialView);
  const [dashboardSymbol, setDashboardSymbol] = useState<string | null>(initialSymbol);

  const [isChartPanelExpanded, setIsChartPanelExpanded] = useState(true);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isSubscribeOpen, setIsSubscribeOpen] = useState(false);
  const [userCollapsed, setUserCollapsed] = useState(false);
  const [marketQuotes, setMarketQuotes] = useState<MarketQuote[]>(
    MARKET_INDICES.map(m => ({ label: m.label, flag: m.flag, loading: true }))
  );
  const { currentTicker, theme, setTheme } = useStore();

  // 右侧面板宽度（从 localStorage 恢复）
  const [panelWidth, setPanelWidth] = useState(() => {
    try {
      const saved = localStorage.getItem(PANEL_WIDTH_STORAGE_KEY);
      if (saved) {
        const parsed = Number(saved);
        if (!Number.isNaN(parsed)) {
          return Math.max(MIN_PANEL_WIDTH, Math.min(MAX_PANEL_WIDTH, parsed));
        }
      }
    } catch {
      // localStorage 不可用
    }
    return DEFAULT_PANEL_WIDTH;
  });
  const panelWidthRef = useRef(panelWidth);

  // 同步 ref 并持久化宽度
  useEffect(() => {
    panelWidthRef.current = panelWidth;
    try {
      localStorage.setItem(PANEL_WIDTH_STORAGE_KEY, String(panelWidth));
    } catch {
      // localStorage 不可用
    }
  }, [panelWidth]);

  // 拖拽调整面板宽度
  const handleResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    const startX = e.clientX;
    const startWidth = panelWidthRef.current;

    const onMouseMove = (moveEvent: MouseEvent) => {
      // 向左拖动 = 增大宽度，向右拖动 = 减小宽度
      const diff = startX - moveEvent.clientX;
      const newWidth = Math.max(MIN_PANEL_WIDTH, Math.min(MAX_PANEL_WIDTH, startWidth + diff));
      setPanelWidth(newWidth);
    };

    const onMouseUp = () => {
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };

    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
  }, []);

  // 切换到 Dashboard 视图
  const openDashboard = (symbol: string) => {
    setDashboardSymbol(symbol);
    setView('dashboard');
    // 更新 URL（不刷新页面）
    const url = new URL(window.location.href);
    url.searchParams.set('symbol', symbol);
    window.history.pushState({}, '', url.toString());
  };

  // 返回 Chat 视图
  const backToChat = () => {
    setView('chat');
    setDashboardSymbol(null);
    // 清除 URL 参数
    const url = new URL(window.location.href);
    url.searchParams.delete('symbol');
    window.history.pushState({}, '', url.toString());
  };

  // 监听浏览器前进/后退
  useEffect(() => {
    const handlePopState = () => {
      const urlParams = new URLSearchParams(window.location.search);
      const symbol = urlParams.get('symbol');
      if (symbol) {
        setDashboardSymbol(symbol);
        setView('dashboard');
      } else {
        setDashboardSymbol(null);
        setView('chat');
      }
    };
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  // 加载市场指数数据
  const loadMarketQuotes = async () => {
    const results = await Promise.all(
      MARKET_INDICES.map(async (item) => {
        try {
          const response = await apiClient.fetchStockPrice(item.ticker);
          const payload = response?.data ?? response;
          const data = payload?.data ?? payload;
          // 解析价格和涨跌幅
          let price: number | undefined;
          let changePct: number | undefined;
          if (typeof data === 'object' && data.price) {
            price = Number(data.price);
            changePct = data.change_percent !== undefined ? Number(data.change_percent) : undefined;
          } else if (typeof data === 'string') {
            const priceMatch = data.match(/\$([0-9.,]+)/);
            const pctMatch = data.match(/\(([-+]?[0-9.]+)%\)/);
            price = priceMatch ? Number(priceMatch[1].replace(/,/g, '')) : undefined;
            changePct = pctMatch ? Number(pctMatch[1]) : undefined;
          }
          return { label: item.label, flag: item.flag, price, changePct, loading: false };
        } catch {
          return { label: item.label, flag: item.flag, loading: false };
        }
      })
    );
    setMarketQuotes(results);
  };

  // 初始加载 + 定时刷新
  useEffect(() => {
    loadMarketQuotes();
    const timer = setInterval(loadMarketQuotes, 60000);
    return () => clearInterval(timer);
  }, []);

  // 生成图表时自动展开右侧面板（仅当用户未手动收起）
  useEffect(() => {
    if (currentTicker && !isChartPanelExpanded && !userCollapsed) {
      setIsChartPanelExpanded(true);
    }
  }, [currentTicker, isChartPanelExpanded, userCollapsed]);

  // ticker 变化时重置手动折叠标记
  useEffect(() => {
    if (currentTicker) {
      setUserCollapsed(false);
    }
  }, [currentTicker]);

  const toggleRightPanel = () => {
    setIsChartPanelExpanded((prev) => {
      const next = !prev;
      setUserCollapsed(!next);
      return next;
    });
  };

  const formatChangePct = (value?: number) => {
    if (value === undefined || Number.isNaN(value)) return null;
    const sign = value >= 0 ? '+' : '';
    return `${sign}${value.toFixed(2)}%`;
  };

  return (
    <div className="flex h-screen w-screen bg-fin-bg text-fin-text font-mono overflow-hidden">
      {/* 1. Sidebar (Fixed width) */}
      <Sidebar
        onSettingsClick={() => setIsSettingsOpen(true)}
        onSubscribeClick={() => setIsSubscribeOpen(true)}
        onDashboardClick={openDashboard}
        onChatClick={backToChat}
        currentView={view}
      />

      {/* 条件渲染: Dashboard 或 Chat 视图 */}
      {view === 'dashboard' ? (
        <div className="flex-1 flex h-full overflow-hidden relative">
          <Dashboard
            initialSymbol={dashboardSymbol ?? undefined}
            onBackToChat={backToChat}
          />
          {/* Dashboard 视图下的可收起右侧面板 */}
          {isChartPanelExpanded && (
            <>
              {/* 拖拽调整宽度手柄 */}
              <div
                className="w-1.5 shrink-0 cursor-col-resize group flex items-center justify-center hover:bg-fin-primary/10 transition-colors"
                onMouseDown={handleResizeStart}
                title="拖拽调整宽度"
              >
                <div className="w-0.5 h-16 rounded-full bg-fin-border group-hover:bg-fin-primary/60 transition-colors" />
              </div>
              <div
                className="shrink-0 flex flex-col gap-4 p-4 bg-fin-bg border-l border-fin-border"
                style={{ width: panelWidth }}
              >
                <RightPanel onCollapse={toggleRightPanel} onSubscribeClick={() => setIsSubscribeOpen(true)} />
              </div>
            </>
          )}
          {!isChartPanelExpanded && (
            <button
              onClick={() => {
                setIsChartPanelExpanded(true);
                setUserCollapsed(false);
              }}
              className="absolute right-2 top-1/2 -translate-y-1/2 z-20 p-2 rounded-full border border-fin-border bg-fin-card text-fin-text-secondary hover:text-fin-primary hover:border-fin-primary transition-colors shadow-sm"
              title="展开右侧面板"
            >
              <ChevronLeft size={16} />
            </button>
          )}
        </div>
      ) : (
        /* 2. Main Workspace (Chat View) */
        <div className="flex-1 flex flex-col h-full overflow-hidden relative">
          {/* Header */}
          <header className="h-[60px] bg-fin-card border-b border-fin-border flex items-center justify-between px-6 shrink-0">
            <div className="flex gap-6 text-xs text-fin-text font-medium">
              {marketQuotes.map((q) => (
                <span key={q.label} className="flex items-center gap-1">
                  {q.flag} {q.label}:{' '}
                  {q.loading ? (
                    <span className="text-fin-muted">...</span>
                  ) : q.changePct !== undefined ? (
                    <span className={q.changePct >= 0 ? 'text-fin-success' : 'text-fin-danger'}>
                      {formatChangePct(q.changePct)}
                    </span>
                  ) : q.price !== undefined ? (
                    <span className="text-fin-warning">${q.price.toLocaleString()}</span>
                  ) : (
                    <span className="text-fin-muted">--</span>
                  )}
                </span>
              ))}
            </div>

            <div className="flex items-center gap-3">
              <button
                onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
                className="p-2 rounded-lg border border-fin-border bg-fin-bg hover:bg-fin-hover transition-colors text-fin-text-secondary"
              >
                {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
              </button>
              <button className="px-3 py-1.5 rounded-lg border border-fin-border bg-fin-bg hover:bg-fin-hover transition-colors text-xs font-medium text-fin-text">
                导出 PDF
              </button>
            </div>
          </header>

          {/* Workspace Grid: Chat + Aux Panel */}
          <div className="flex-1 flex overflow-hidden p-5 gap-5">
            {/* Left: Chat Interaction */}
            <div className="flex-1 bg-fin-card border border-fin-border rounded-2xl flex flex-col overflow-hidden shadow-sm">
              <ChatList />
              <ChatInput onDashboardRequest={openDashboard} />
            </div>

            {/* Right: Auxiliary Panel (Visualization & Context) */}
            {isChartPanelExpanded && (
              <>
                {/* 拖拽调整宽度手柄 */}
                <div
                  className="w-1.5 shrink-0 cursor-col-resize group flex items-center justify-center hover:bg-fin-primary/10 transition-colors"
                  onMouseDown={handleResizeStart}
                  title="拖拽调整宽度"
                >
                  <div className="w-0.5 h-16 rounded-full bg-fin-border group-hover:bg-fin-primary/60 transition-colors" />
                </div>
                <div
                  className="shrink-0 flex flex-col gap-4"
                  style={{ width: panelWidth }}
                >
                  <RightPanel onCollapse={toggleRightPanel} onSubscribeClick={() => setIsSubscribeOpen(true)} showMiniChat={false} />
                </div>
              </>
            )}
            {!isChartPanelExpanded && (
              <button
                onClick={() => {
                  setIsChartPanelExpanded(true);
                  setUserCollapsed(false);
                }}
                className="absolute right-2 top-1/2 -translate-y-1/2 z-20 p-2 rounded-full border border-fin-border bg-fin-card text-fin-text-secondary hover:text-fin-primary hover:border-fin-primary transition-colors shadow-sm"
                title="展开右侧面板"
              >
                <ChevronLeft size={16} />
              </button>
            )}
          </div>
        </div>
      )}

      <SettingsModal isOpen={isSettingsOpen} onClose={() => setIsSettingsOpen(false)} />
      <SubscribeModal isOpen={isSubscribeOpen} onClose={() => setIsSubscribeOpen(false)} />
    </div>
  );
}

export default App;
