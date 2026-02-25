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
import { useToast } from '../ui/Toast';
import { API_BASE_URL } from '../../config/runtime';
import { ChatWorkspace } from './ChatWorkspace';
import { DashboardWorkspace } from './DashboardWorkspace';
import { WorkbenchWorkspace } from './WorkbenchWorkspace';
import { ExecutionBanner } from '../execution/ExecutionBanner';

export type WorkspaceView = 'chat' | 'dashboard' | 'workbench';

type WorkspaceShellProps = {
  view: WorkspaceView;
  dashboardSymbol: string | null;
  initialReportId?: string | null;
  navigateToChat: () => void;
  navigateToDashboard: (symbol: string) => void;
  navigateToWorkbench: () => void;
};

const DEFAULT_PANEL_WIDTH = 380;
const MIN_PANEL_WIDTH = 280;
const MAX_PANEL_WIDTH = 600;
const PANEL_WIDTH_STORAGE_KEY = 'finsight_right_panel_width';

const getDynamicPanelMaxWidth = () => {
  if (typeof window === 'undefined') return MAX_PANEL_WIDTH;
  const viewport = window.innerWidth || 0;
  if (!viewport) return MAX_PANEL_WIDTH;

  // 预留左侧导航与主内容空间，避免右侧面板把中间布局“挤飞”。
  const ratioBound = Math.floor(viewport * 0.38);
  const reserveBound = viewport - 760;
  const dynamicMax = Math.min(MAX_PANEL_WIDTH, ratioBound, reserveBound);
  return Math.max(MIN_PANEL_WIDTH, dynamicMax);
};

const clampPanelWidth = (value: number, maxWidth = getDynamicPanelMaxWidth()) =>
  Math.max(MIN_PANEL_WIDTH, Math.min(maxWidth, value));

export function WorkspaceShell({
  view,
  dashboardSymbol,
  initialReportId,
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
  const { theme, setTheme, showRightPanel, setShowRightPanel } = useStore();
  const { quotes: marketQuotes } = useMarketQuotes();
  const { toast } = useToast();

  // 启动时检查 dry_run 状态并提示用户
  useEffect(() => {
    const checkDryRun = async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/health`);
        const data = await res.json();
        if (data?.components?.live_tools?.status === 'dry_run') {
          toast({
            type: 'warning',
            title: 'Dry-run 模式',
            message: '当前为模拟模式，不执行实际工具调用。设置 LANGGRAPH_EXECUTE_LIVE_TOOLS=true 启用。',
            duration: 8000,
          });
        }
      } catch {
        // 健康检查失败时静默忽略
      }
    };
    checkDryRun();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  // No AAPL fallback — empty string means "no symbol selected"
  const preferredSymbol = (view === 'workbench' ? (workbenchSymbol || dashboardSymbol) : dashboardSymbol) || '';

  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isSubscribeOpen, setIsSubscribeOpen] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [panelWidth, setPanelWidth] = useState(() => {
    try {
      const saved = localStorage.getItem(PANEL_WIDTH_STORAGE_KEY);
      if (saved) {
        const parsed = Number(saved);
        if (!Number.isNaN(parsed)) {
          return clampPanelWidth(parsed, getDynamicPanelMaxWidth());
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

  useEffect(() => {
    const handleOpenSettings = () => setIsSettingsOpen(true);
    window.addEventListener('finsight:open-settings', handleOpenSettings as EventListener);
    return () => {
      window.removeEventListener('finsight:open-settings', handleOpenSettings as EventListener);
    };
  }, []);

  const handleResizeStart = useCallback(
    (event: MouseEvent) => {
      if (isMobile) return;
      event.preventDefault();
      const startX = event.clientX;
      const startWidth = panelWidthRef.current;

      const onMouseMove = (moveEvent: globalThis.MouseEvent) => {
        const diff = startX - moveEvent.clientX;
        setPanelWidth(clampPanelWidth(startWidth + diff, getDynamicPanelMaxWidth()));
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

  useEffect(() => {
    if (isMobile) return;
    const onResize = () => {
      setPanelWidth((prev) => clampPanelWidth(prev, getDynamicPanelMaxWidth()));
    };
    window.addEventListener('resize', onResize);
    return () => {
      window.removeEventListener('resize', onResize);
    };
  }, [isMobile]);

  const openDashboard = (symbol: string) => {
    const normalized = symbol.trim();
    if (!normalized) return;
    navigateToDashboard(normalized);
  };

  const contextPanelProps = {
    panelWidth,
    isExpanded: showRightPanel,
    onExpand: () => setShowRightPanel(true),
    onCollapse: () => setShowRightPanel(false),
    onResizeStart: handleResizeStart,
    onSubscribeClick: () => setIsSubscribeOpen(true),
    autoSwitchExecution: true,
    onNavigateToChat: navigateToChat,
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

      <div id="main-content" className="flex-1 min-w-0 flex flex-col min-h-0 overflow-hidden">
        <ExecutionBanner />

        <div className="flex-1 min-w-0 min-h-0 overflow-hidden">
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
            <WorkbenchWorkspace
              isMobile={isMobile}
              symbol={preferredSymbol}
              fromDashboard={fromDashboard}
              onNavigateToChat={navigateToChat}
              contextPanel={contextPanelProps}
            />
          ) : (
            <ChatWorkspace
              isMobile={isMobile}
              theme={theme}
              onToggleTheme={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
              onDashboardRequest={openDashboard}
              contextPanel={contextPanelProps}
              marketQuotes={marketQuotes}
              initialReportId={initialReportId}
            />
          )}
        </div>
      </div>

      <SettingsModal isOpen={isSettingsOpen} onClose={() => setIsSettingsOpen(false)} />
      <SubscribeModal isOpen={isSubscribeOpen} onClose={() => setIsSubscribeOpen(false)} />
    </div>
  );
}
