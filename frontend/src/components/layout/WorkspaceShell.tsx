import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import type { MouseEvent } from 'react';
import { Menu } from 'lucide-react';
import Sidebar from '../Sidebar';
import { SettingsModal } from '../SettingsModal';
import { SubscribeModal } from '../SubscribeModal';
import { useStore } from '../../store/useStore';
import { useIsMobileLayout } from '../../hooks/useIsMobileLayout';
import { useMarketQuotes } from '../../hooks/useMarketQuotes';
import { ChatWorkspace } from './ChatWorkspace';
import { DashboardWorkspace } from './DashboardWorkspace';
import Workbench from '../../pages/Workbench';
import { useDashboardData } from '../../hooks/useDashboardData';
import { useDashboardStore } from '../../store/dashboardStore';

export type WorkspaceView = 'chat' | 'dashboard' | 'workbench';

type WorkspaceShellProps = {
  view: WorkspaceView;
  dashboardSymbol: string | null;
  navigateToChat: () => void;
  navigateToDashboard: (symbol: string) => void;
  navigateToWorkbench: () => void;
};

const DEFAULT_PANEL_WIDTH = 380;
const MIN_PANEL_WIDTH = 280;
const MAX_PANEL_WIDTH = 600;
const PANEL_WIDTH_STORAGE_KEY = 'finsight_right_panel_width';

const clampPanelWidth = (value: number) => Math.max(MIN_PANEL_WIDTH, Math.min(MAX_PANEL_WIDTH, value));

export function WorkspaceShell({
  view,
  dashboardSymbol,
  navigateToChat,
  navigateToDashboard,
  navigateToWorkbench,
}: WorkspaceShellProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const workbenchParams = new URLSearchParams(location.search);
  const fromDashboard = workbenchParams.get('from') === 'dashboard';
  const workbenchSymbol = (workbenchParams.get('symbol') || '').trim() || null;

  const isMobile = useIsMobileLayout();
  const { theme, setTheme } = useStore();
  const { quotes: marketQuotes } = useMarketQuotes();
  const { dashboardData } = useDashboardStore();
  const preferredSymbol = (view === 'workbench' ? (workbenchSymbol || dashboardSymbol) : dashboardSymbol) || 'AAPL';
  useDashboardData(view === 'workbench' ? preferredSymbol : null);

  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isSubscribeOpen, setIsSubscribeOpen] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [isContextPanelExpanded, setIsContextPanelExpanded] = useState(true);
  const [panelWidth, setPanelWidth] = useState(() => {
    try {
      const saved = localStorage.getItem(PANEL_WIDTH_STORAGE_KEY);
      if (saved) {
        const parsed = Number(saved);
        if (!Number.isNaN(parsed)) {
          return clampPanelWidth(parsed);
        }
      }
    } catch {
      // localStorage unavailable
    }
    return DEFAULT_PANEL_WIDTH;
  });

  const panelWidthRef = useRef(panelWidth);
  useEffect(() => {
    panelWidthRef.current = panelWidth;
    try {
      localStorage.setItem(PANEL_WIDTH_STORAGE_KEY, String(panelWidth));
    } catch {
      // localStorage unavailable
    }
  }, [panelWidth]);

  const handleResizeStart = useCallback(
    (event: MouseEvent) => {
      if (isMobile) return;
      event.preventDefault();
      const startX = event.clientX;
      const startWidth = panelWidthRef.current;

      const onMouseMove = (moveEvent: globalThis.MouseEvent) => {
        const diff = startX - moveEvent.clientX;
        setPanelWidth(clampPanelWidth(startWidth + diff));
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
    navigateToDashboard(normalized);
  };

  const contextPanelProps = {
    panelWidth,
    isExpanded: isContextPanelExpanded,
    onExpand: () => setIsContextPanelExpanded(true),
    onCollapse: () => setIsContextPanelExpanded(false),
    onResizeStart: handleResizeStart,
    onSubscribeClick: () => setIsSubscribeOpen(true),
  };

  return (
    <div className="flex h-screen w-screen bg-fin-bg text-fin-text font-mono overflow-hidden">
      {/* Mobile menu button */}
      {isMobile && (
        <button
          onClick={() => setIsSidebarOpen(true)}
          className="fixed top-3 left-3 z-50 p-2 rounded-lg bg-fin-card border border-fin-border text-fin-text hover:bg-fin-hover transition-colors lg:hidden"
          aria-label="打开导航菜单"
        >
          <Menu size={20} />
        </button>
      )}
      <Sidebar
        onSettingsClick={() => setIsSettingsOpen(true)}
        onSubscribeClick={() => setIsSubscribeOpen(true)}
        onDashboardClick={(s) => { openDashboard(s); setIsSidebarOpen(false); }}
        onChatClick={() => { navigateToChat(); setIsSidebarOpen(false); }}
        onWorkbenchClick={() => { navigateToWorkbench(); setIsSidebarOpen(false); }}
        currentView={view}
        isMobileOpen={isSidebarOpen}
        onMobileClose={() => setIsSidebarOpen(false)}
      />

      {view === 'dashboard' ? (
        <DashboardWorkspace
          isMobile={isMobile}
          symbol={dashboardSymbol}
          onBackToChat={navigateToChat}
          onSymbolChange={openDashboard}
          onGoWorkbench={(symbol) => {
            const normalized = symbol.trim();
            if (!normalized) {
              navigate('/workbench?from=dashboard');
              return;
            }
            navigate(`/workbench?from=dashboard&symbol=${encodeURIComponent(normalized)}`);
          }}
          contextPanel={contextPanelProps}
        />
      ) : view === 'workbench' ? (
        <div className="flex-1 min-w-0 min-h-0 overflow-y-auto p-5 max-lg:p-3">
          <Workbench
            symbol={preferredSymbol}
            fromDashboard={fromDashboard}
            newsItems={dashboardData?.news?.impact || []}
            rawNewsItems={dashboardData?.news?.impact_raw || []}
            rankingMeta={
              typeof dashboardData?.news?.ranking_meta === 'object'
                ? {
                    version: (dashboardData.news.ranking_meta as { version?: string }).version,
                    formula: (dashboardData.news.ranking_meta as { formula?: string }).formula,
                    notes: Array.isArray((dashboardData.news.ranking_meta as { notes?: unknown[] }).notes)
                      ? ((dashboardData.news.ranking_meta as { notes?: string[] }).notes || [])
                      : [],
                  }
                : undefined
            }
          />
        </div>
      ) : (
        <ChatWorkspace
          isMobile={isMobile}
          theme={theme}
          onToggleTheme={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
          onDashboardRequest={openDashboard}
          contextPanel={contextPanelProps}
          marketQuotes={marketQuotes}
        />
      )}

      <SettingsModal isOpen={isSettingsOpen} onClose={() => setIsSettingsOpen(false)} />
      <SubscribeModal isOpen={isSubscribeOpen} onClose={() => setIsSubscribeOpen(false)} />
    </div>
  );
}


