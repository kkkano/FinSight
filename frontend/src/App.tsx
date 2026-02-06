import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Navigate, Route, Routes, useLocation, useNavigate, useParams } from 'react-router-dom';
import { Sun, Moon, ChevronLeft } from 'lucide-react';
import Sidebar from './components/Sidebar';
import { ChatList } from './components/ChatList';
import { ChatInput } from './components/ChatInput';
import { RightPanel } from './components/RightPanel';
import { AgentLogPanel } from './components/AgentLogPanel';
import { SettingsModal } from './components/SettingsModal';
import { SubscribeModal } from './components/SubscribeModal';
import { Dashboard } from './pages/Dashboard';
import { useStore } from './store/useStore';
import { apiClient } from './api/client';

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

type ViewType = 'chat' | 'dashboard';

const DEFAULT_PANEL_WIDTH = 380;
const MIN_PANEL_WIDTH = 280;
const MAX_PANEL_WIDTH = 600;
const PANEL_WIDTH_STORAGE_KEY = 'finsight_right_panel_width';

const MOBILE_BREAKPOINT = 1024;

const decodeSymbolParam = (raw?: string): string | null => {
  if (!raw) return null;
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
};

const useIsMobileLayout = () => {
  const [isMobile, setIsMobile] = useState(() =>
    typeof window !== 'undefined' ? window.innerWidth < MOBILE_BREAKPOINT : false,
  );

  useEffect(() => {
    const onResize = () => setIsMobile(window.innerWidth < MOBILE_BREAKPOINT);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  return isMobile;
};

function WorkspaceShell({ view, dashboardSymbol }: { view: ViewType; dashboardSymbol: string | null }) {
  const navigate = useNavigate();
  const isMobile = useIsMobileLayout();

  const [isContextPanelExpanded, setIsContextPanelExpanded] = useState(true);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isSubscribeOpen, setIsSubscribeOpen] = useState(false);
  const [marketQuotes, setMarketQuotes] = useState<MarketQuote[]>(
    MARKET_INDICES.map((m) => ({ label: m.label, flag: m.flag, loading: true })),
  );
  const { theme, setTheme } = useStore();

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
      // localStorage not available
    }
    return DEFAULT_PANEL_WIDTH;
  });
  const panelWidthRef = useRef(panelWidth);

  useEffect(() => {
    panelWidthRef.current = panelWidth;
    try {
      localStorage.setItem(PANEL_WIDTH_STORAGE_KEY, String(panelWidth));
    } catch {
      // localStorage not available
    }
  }, [panelWidth]);

  const handleResizeStart = useCallback(
    (event: React.MouseEvent) => {
      if (isMobile) return;

      event.preventDefault();
      const startX = event.clientX;
      const startWidth = panelWidthRef.current;

      const onMouseMove = (moveEvent: MouseEvent) => {
        const diff = startX - moveEvent.clientX;
        const nextWidth = Math.max(MIN_PANEL_WIDTH, Math.min(MAX_PANEL_WIDTH, startWidth + diff));
        setPanelWidth(nextWidth);
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
    },
    [isMobile],
  );

  const openDashboard = (symbol: string) => {
    const normalized = symbol.trim();
    if (!normalized) return;
    navigate(`/dashboard/${encodeURIComponent(normalized)}`);
  };

  const handleDashboardSymbolChange = (symbol: string) => {
    const normalized = symbol.trim();
    if (!normalized) return;
    navigate(`/dashboard/${encodeURIComponent(normalized)}`);
  };

  const backToChat = () => {
    navigate('/chat');
  };

  const loadMarketQuotes = useCallback(async () => {
    const results = await Promise.all(
      MARKET_INDICES.map(async (item) => {
        try {
          const response = await apiClient.fetchStockPrice(item.ticker);
          const payload = response?.data ?? response;
          const data = payload?.data ?? payload;
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
      }),
    );
    setMarketQuotes(results);
  }, []);

  useEffect(() => {
    loadMarketQuotes();
    const timer = setInterval(loadMarketQuotes, 60_000);
    return () => clearInterval(timer);
  }, [loadMarketQuotes]);

  const formatChangePct = (value?: number) => {
    if (value === undefined || Number.isNaN(value)) return null;
    const sign = value >= 0 ? '+' : '';
    return `${sign}${value.toFixed(2)}%`;
  };

  const contextPanelShellClass = useMemo(
    () =>
      isMobile
        ? 'w-full shrink-0 border-t border-fin-border bg-fin-bg p-3 max-h-[48vh] min-h-[320px]'
        : 'h-full shrink-0 border-l border-fin-border bg-fin-bg p-4',
    [isMobile],
  );

  const renderContextPanel = (showMiniChat: boolean) => {
    if (!isContextPanelExpanded) return null;

    return (
      <>
        {!isMobile && (
          <div
            className="w-1.5 shrink-0 cursor-col-resize group flex items-center justify-center hover:bg-fin-primary/10 transition-colors"
            onMouseDown={handleResizeStart}
            title="拖拽调整宽度"
          >
            <div className="w-0.5 h-16 rounded-full bg-fin-border group-hover:bg-fin-primary/60 transition-colors" />
          </div>
        )}

        <aside
          data-testid="context-panel-shell"
          className={contextPanelShellClass}
          style={!isMobile ? { width: panelWidth } : undefined}
        >
          <RightPanel
            onCollapse={() => setIsContextPanelExpanded(false)}
            onSubscribeClick={() => setIsSubscribeOpen(true)}
            showMiniChat={showMiniChat}
            className="h-full"
          />
        </aside>
      </>
    );
  };

  const renderExpandContextButton = () => {
    if (isContextPanelExpanded) return null;

    return (
      <button
        type="button"
        data-testid="context-panel-expand"
        onClick={() => setIsContextPanelExpanded(true)}
        className="absolute right-2 top-1/2 -translate-y-1/2 z-20 p-2 rounded-full border border-fin-border bg-fin-card text-fin-text-secondary hover:text-fin-primary hover:border-fin-primary transition-colors shadow-sm"
        title="展开右侧面板"
      >
        <ChevronLeft size={16} />
      </button>
    );
  };

  return (
    <div className="flex h-screen w-screen bg-fin-bg text-fin-text font-mono overflow-hidden max-lg:flex-col">
      <Sidebar
        onSettingsClick={() => setIsSettingsOpen(true)}
        onSubscribeClick={() => setIsSubscribeOpen(true)}
        onDashboardClick={openDashboard}
        onChatClick={backToChat}
        currentView={view}
      />

      {view === 'dashboard' ? (
        <div className="flex-1 min-w-0 flex min-h-0 overflow-hidden relative max-lg:flex-col">
          <div className="flex-1 min-w-0 min-h-0 flex flex-col overflow-hidden">
            <Dashboard
              initialSymbol={dashboardSymbol ?? undefined}
              onBackToChat={backToChat}
              onSymbolChange={handleDashboardSymbolChange}
            />
            <div className="shrink-0 px-4 pb-4 max-lg:px-3 max-lg:pb-3">
              <AgentLogPanel />
            </div>
          </div>

          {renderContextPanel(true)}
          {renderExpandContextButton()}
        </div>
      ) : (
        <div className="flex-1 min-w-0 flex flex-col h-full overflow-hidden relative">
          <header className="h-[60px] bg-fin-card border-b border-fin-border flex items-center justify-between px-6 shrink-0 max-lg:px-3">
            <div className="flex gap-4 text-xs text-fin-text font-medium overflow-x-auto scrollbar-none">
              {marketQuotes.map((quote) => (
                <span key={quote.label} className="flex items-center gap-1 whitespace-nowrap">
                  {quote.flag} {quote.label}:{' '}
                  {quote.loading ? (
                    <span className="text-fin-muted">...</span>
                  ) : quote.changePct !== undefined ? (
                    <span className={quote.changePct >= 0 ? 'text-fin-success' : 'text-fin-danger'}>
                      {formatChangePct(quote.changePct)}
                    </span>
                  ) : quote.price !== undefined ? (
                    <span className="text-fin-warning">${quote.price.toLocaleString()}</span>
                  ) : (
                    <span className="text-fin-muted">--</span>
                  )}
                </span>
              ))}
            </div>

            <div className="flex items-center gap-3 shrink-0">
              <button
                type="button"
                onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
                className="p-2 rounded-lg border border-fin-border bg-fin-bg hover:bg-fin-hover transition-colors text-fin-text-secondary"
              >
                {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
              </button>
              <button
                type="button"
                className="px-3 py-1.5 rounded-lg border border-fin-border bg-fin-bg hover:bg-fin-hover transition-colors text-xs font-medium text-fin-text"
              >
                导出 PDF
              </button>
            </div>
          </header>

          <div className="flex-1 min-h-0 flex overflow-hidden p-5 gap-4 max-lg:flex-col max-lg:p-3">
            <div className="flex-1 min-w-0 min-h-0 flex flex-col gap-3 overflow-hidden">
              <div className="flex-1 bg-fin-card border border-fin-border rounded-2xl flex flex-col overflow-hidden shadow-sm min-h-0">
                <ChatList />
                <ChatInput onDashboardRequest={openDashboard} />
              </div>
              <div className="shrink-0">
                <AgentLogPanel />
              </div>
            </div>

            {renderContextPanel(false)}
            {renderExpandContextButton()}
          </div>
        </div>
      )}

      <SettingsModal isOpen={isSettingsOpen} onClose={() => setIsSettingsOpen(false)} />
      <SubscribeModal isOpen={isSubscribeOpen} onClose={() => setIsSubscribeOpen(false)} />
    </div>
  );
}

function ChatRoute() {
  return <WorkspaceShell view="chat" dashboardSymbol={null} />;
}

function DashboardRoute() {
  const { symbol } = useParams();
  return <WorkspaceShell view="dashboard" dashboardSymbol={decodeSymbolParam(symbol)} />;
}

function RootRedirect() {
  const location = useLocation();
  const params = new URLSearchParams(location.search);
  const symbol = params.get('symbol');

  if (symbol && symbol.trim()) {
    return <Navigate to={{ pathname: `/dashboard/${encodeURIComponent(symbol.trim())}`, search: '' }} replace />;
  }

  return <Navigate to={{ pathname: '/chat', search: '' }} replace />;
}

function App() {
  return (
    <Routes>
      <Route path="/" element={<RootRedirect />} />
      <Route path="/chat" element={<ChatRoute />} />
      <Route path="/dashboard" element={<DashboardRoute />} />
      <Route path="/dashboard/:symbol" element={<DashboardRoute />} />
      <Route path="*" element={<Navigate to="/chat" replace />} />
    </Routes>
  );
}

export default App;
