import { useEffect, useRef, useState } from 'react';
import type { FC } from 'react';

import { ExecutionPanel } from './execution/ExecutionPanel';
import { RightPanelChartTab } from './right-panel/RightPanelChartTab';
import { RightPanelHeader } from './right-panel/RightPanelHeader';
import type { RightPanelTab } from './right-panel/types';
import { useExecutionStore } from '../store/executionStore';
import { useStore } from '../store/useStore';
import { RightPanelTrackRecordTab } from './right-panel/RightPanelTrackRecordTab';

type RightPanelProps = {
  onCollapse: () => void;
  autoSwitchExecution?: boolean;
  className?: string;
  detailExpanded?: boolean;
  onToggleExpanded?: () => void;
  symbol?: string;
};

export const RightPanel: FC<RightPanelProps> = ({
  onCollapse,
  autoSwitchExecution = true,
  className,
  detailExpanded = false,
  onToggleExpanded,
  symbol,
}) => {
  const activeRuns = useExecutionStore((state) => state.activeRuns);
  const recentRuns = useExecutionStore((state) => state.recentRuns);
  const activeTab = useStore((state) => state.rightPanelTab);
  const setActiveTab = useStore((state) => state.setRightPanelTab);
  const [userPinnedTab, setUserPinnedTab] = useState<RightPanelTab | null>(null);
  const [hasUnseenExecution, setHasUnseenExecution] = useState(false);
  const previousActiveCount = useRef(activeRuns.length);

  useEffect(() => {
    if (!autoSwitchExecution) {
      previousActiveCount.current = activeRuns.length;
      return;
    }
    const hasNewRun = previousActiveCount.current === 0 && activeRuns.length > 0;
    if (hasNewRun && activeTab !== 'track-record' && userPinnedTab !== 'chart') {
      setActiveTab('execution');
      setHasUnseenExecution(false);
    } else if (hasNewRun) {
      setHasUnseenExecution(true);
    }
    if (previousActiveCount.current > 0 && activeRuns.length === 0) {
      setUserPinnedTab(null);
      setHasUnseenExecution(false);
    }
    previousActiveCount.current = activeRuns.length;
  }, [activeRuns.length, activeTab, autoSwitchExecution, setActiveTab, userPinnedTab]);

  const latestRunId = activeRuns.at(-1)?.runId ?? recentRuns[0]?.runId ?? null;

  return (
    <section
      data-testid="context-panel"
      className={`flex h-full min-h-0 flex-col overflow-hidden bg-t-surface ${className || ''}`}
    >
      <RightPanelHeader
        activeTab={activeTab}
        executionCount={activeRuns.length}
        hasUnseenExecution={hasUnseenExecution}
        onTabChange={(tab) => {
          setActiveTab(tab);
          setUserPinnedTab(tab);
          if (tab === 'execution') setHasUnseenExecution(false);
        }}
        onCollapse={onCollapse}
        isExpanded={detailExpanded}
        onToggleExpanded={onToggleExpanded}
      />
      <div className="min-h-0 flex-1 overflow-hidden">
        {activeTab === 'chart' ? (
          <RightPanelChartTab symbol={symbol} />
        ) : activeTab === 'execution' ? (
          <div className="h-full overflow-y-auto p-3">
            <ExecutionPanel runId={latestRunId} compact className="border-0 bg-transparent p-0" />
          </div>
        ) : (
          <div className="h-full overflow-y-auto">
            <RightPanelTrackRecordTab symbol={symbol} />
          </div>
        )}
      </div>
    </section>
  );
};
