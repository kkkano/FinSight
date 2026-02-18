import { useEffect, useRef, useState } from 'react';
import type { FC } from 'react';
import { MiniChat } from './MiniChat';
import { RightPanelHeader } from './right-panel/RightPanelHeader';
import { RightPanelAlertsTab } from './right-panel/RightPanelAlertsTab';
import { RightPanelPortfolioTab } from './right-panel/RightPanelPortfolioTab';
import { RightPanelChartTab } from './right-panel/RightPanelChartTab';
import { StreamingResultPanel } from './execution/StreamingResultPanel';
import { useRightPanelData } from './right-panel/useRightPanelData';
import { useExecutionStore } from '../store/executionStore';
import type { RightPanelTab } from './right-panel/types';

type RightPanelProps = {
  onCollapse: () => void;
  onSubscribeClick?: () => void;
  onNavigateToChat?: () => void;
  showMiniChat?: boolean;
  autoSwitchExecution?: boolean;
  className?: string;
};

export const RightPanel: FC<RightPanelProps> = ({
  onCollapse,
  onSubscribeClick,
  onNavigateToChat,
  showMiniChat = true,
  autoSwitchExecution = true,
  className,
}) => {
  const [activeTab, setActiveTab] = useState<RightPanelTab>(() =>
    useExecutionStore.getState().activeRuns.length > 0 ? 'execution' : 'alerts',
  );
  const [userPinnedTab, setUserPinnedTab] = useState<RightPanelTab | null>(null);
  const {
    alerts,
    alertEvents,
    emailConfigured,
    alertsLoading,
    alertsError,
    unreadAlertCount,
    markAlertsRead,
    loading,
    lastUpdated,
    refreshAll,
    positionRows,
    portfolioSummary,
    isPortfolioEditing,
    positionDrafts,
    setPositionDrafts,
    startPortfolioEdit,
    cancelPortfolioEdit,
    savePortfolioEdit,
  } = useRightPanelData();

  // Execution state for tab badge and auto-switch
  const activeRuns = useExecutionStore((s) => s.activeRuns);
  const recentRuns = useExecutionStore((s) => s.recentRuns);

  const handleTabChange = (tab: RightPanelTab) => {
    setActiveTab(tab);
    setUserPinnedTab(tab);
  };

  // Latest runId for StreamingResultPanel
  const latestRunId = activeRuns.length > 0
    ? activeRuns[activeRuns.length - 1].runId
    : recentRuns.length > 0
      ? recentRuns[recentRuns.length - 1].runId
      : null;

  // Auto-switch to execution tab ONLY on 0→N transition
  const prevActiveCountRef = useRef(activeRuns.length);
  useEffect(() => {
    if (!autoSwitchExecution) {
      prevActiveCountRef.current = activeRuns.length;
      return;
    }
    const hasNewRun = prevActiveCountRef.current === 0 && activeRuns.length > 0;
    const pinnedNonExecution = userPinnedTab !== null && userPinnedTab !== 'execution';
    if (hasNewRun && !pinnedNonExecution) {
      setActiveTab('execution');
    }
    if (prevActiveCountRef.current > 0 && activeRuns.length === 0) {
      setUserPinnedTab(null);
    }
    prevActiveCountRef.current = activeRuns.length;
  }, [activeRuns.length, autoSwitchExecution, userPinnedTab]);

  useEffect(() => {
    if (activeTab === 'alerts') {
      markAlertsRead();
    }
  }, [activeTab, markAlertsRead]);

  return (
    <section
      data-testid="context-panel"
      className={`flex flex-col h-full bg-fin-card border border-fin-border rounded-xl shadow-sm overflow-hidden ${className || ''}`}
    >
      <RightPanelHeader
        activeTab={activeTab}
        alertsCount={unreadAlertCount}
        executionCount={activeRuns.length}
        loading={loading}
        onTabChange={handleTabChange}
        onRefresh={refreshAll}
        onCollapse={onCollapse}
      />

      <div className="flex-1 min-h-0 overflow-hidden">
        {activeTab === 'alerts' && (
          <RightPanelAlertsTab
            subscriptions={alerts}
            events={alertEvents}
            emailConfigured={emailConfigured}
            unreadCount={unreadAlertCount}
            loading={alertsLoading}
            error={alertsError}
            onRetry={refreshAll}
            onMarkRead={markAlertsRead}
            onSubscribeClick={onSubscribeClick}
          />
        )}
        {activeTab === 'portfolio' && (
          <RightPanelPortfolioTab
            positionRows={positionRows}
            portfolioSummary={portfolioSummary}
            isPortfolioEditing={isPortfolioEditing}
            positionDrafts={positionDrafts}
            setPositionDrafts={setPositionDrafts}
            onStartPortfolioEdit={startPortfolioEdit}
            onCancelPortfolioEdit={cancelPortfolioEdit}
            onSavePortfolioEdit={savePortfolioEdit}
          />
        )}
        {activeTab === 'chart' && <RightPanelChartTab />}
        {activeTab === 'execution' && (
          <div className="h-full overflow-y-auto p-3">
            <StreamingResultPanel runId={latestRunId} compact onNavigateToChat={onNavigateToChat} />
          </div>
        )}
      </div>

      {showMiniChat && (
        <div className="h-[45%] min-h-[180px] border-t border-fin-border flex flex-col">
          <MiniChat />
        </div>
      )}

      {lastUpdated && (
        <div className="text-2xs text-fin-muted text-center py-1 border-t border-fin-border/50 shrink-0">
          Last updated: {lastUpdated.toLocaleTimeString()}
        </div>
      )}
    </section>
  );
};
