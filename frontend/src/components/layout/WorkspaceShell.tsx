import { useCallback, useEffect, useRef, useState } from 'react';
import type { MouseEvent } from 'react';
import Sidebar from '../Sidebar';
import { SettingsModal } from '../SettingsModal';
import { SubscribeModal } from '../SubscribeModal';
import { useStore } from '../../store/useStore';
import { useIsMobileLayout } from '../../hooks/useIsMobileLayout';
import { useMarketQuotes } from '../../hooks/useMarketQuotes';
import { ChatWorkspace } from './ChatWorkspace';
import { DashboardWorkspace } from './DashboardWorkspace';

export type WorkspaceView = 'chat' | 'dashboard';

type WorkspaceShellProps = {
  view: WorkspaceView;
  dashboardSymbol: string | null;
  navigateToChat: () => void;
  navigateToDashboard: (symbol: string) => void;
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
}: WorkspaceShellProps) {
  const isMobile = useIsMobileLayout();
  const { theme, setTheme } = useStore();
  const { quotes: marketQuotes } = useMarketQuotes();

  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isSubscribeOpen, setIsSubscribeOpen] = useState(false);
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
    <div className="flex h-screen w-screen bg-fin-bg text-fin-text font-mono overflow-hidden max-lg:flex-col">
      <Sidebar
        onSettingsClick={() => setIsSettingsOpen(true)}
        onSubscribeClick={() => setIsSubscribeOpen(true)}
        onDashboardClick={openDashboard}
        onChatClick={navigateToChat}
        currentView={view}
      />

      {view === 'dashboard' ? (
        <DashboardWorkspace
          isMobile={isMobile}
          symbol={dashboardSymbol}
          onBackToChat={navigateToChat}
          onSymbolChange={openDashboard}
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
        />
      )}

      <SettingsModal isOpen={isSettingsOpen} onClose={() => setIsSettingsOpen(false)} />
      <SubscribeModal isOpen={isSubscribeOpen} onClose={() => setIsSubscribeOpen(false)} />
    </div>
  );
}

