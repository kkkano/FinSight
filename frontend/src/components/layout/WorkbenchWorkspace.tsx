import type { MouseEvent } from 'react';

import { AgentLogPanel } from '../agent-log';
import { ExecutionPanel } from '../execution/ExecutionPanel';
import Workbench from '../../pages/Workbench';
import { useExecutionStore } from '../../store/executionStore';
import { useStore } from '../../store/useStore';
import { ContextPanelShell } from './ContextPanelShell';

type WorkbenchWorkspaceProps = {
  isMobile: boolean;
  symbol: string;
  fromDashboard: boolean;
  onNavigateToChat?: () => void;
  contextPanel: {
    panelWidth: number;
    isExpanded: boolean;
    onExpand: () => void;
    onCollapse: () => void;
    onResizeStart: (event: MouseEvent) => void;
    onSubscribeClick: () => void;
    autoSwitchExecution?: boolean;
    onNavigateToChat?: () => void;
  };
};

export function WorkbenchWorkspace({
  isMobile,
  symbol,
  fromDashboard,
  onNavigateToChat,
  contextPanel,
}: WorkbenchWorkspaceProps) {
  const traceViewMode = useStore((state) => state.traceViewMode);
  const latestRunId = useExecutionStore((state) => (
    state.activeRuns[state.activeRuns.length - 1]?.runId
      ?? state.recentRuns[0]?.runId
      ?? null
  ));

  return (
    <div className="h-full flex-1 min-w-0 flex min-h-0 overflow-hidden relative max-lg:flex-col">
      <div className="h-full flex-1 min-w-0 min-h-0 flex flex-col overflow-hidden">
        <div className="flex-1 min-h-0 overflow-y-auto p-5 max-lg:p-3">
          <Workbench
            symbol={symbol}
            fromDashboard={fromDashboard}
            onNavigateToChat={onNavigateToChat}
          />
        </div>
        <div className="shrink-0 px-5 pb-5 max-lg:px-3 max-lg:pb-3">
          {traceViewMode === 'dev' ? (
            <AgentLogPanel />
          ) : (
            <ExecutionPanel
              runId={latestRunId}
              mode={traceViewMode === 'expert' ? 'expert' : 'user'}
            />
          )}
        </div>
      </div>

      <ContextPanelShell
        isMobile={isMobile}
        panelWidth={contextPanel.panelWidth}
        isExpanded={contextPanel.isExpanded}
        onExpand={contextPanel.onExpand}
        onCollapse={contextPanel.onCollapse}
        onResizeStart={contextPanel.onResizeStart}
        onSubscribeClick={contextPanel.onSubscribeClick}
        autoSwitchExecution={contextPanel.autoSwitchExecution}
        onNavigateToChat={contextPanel.onNavigateToChat}
        showMiniChat
      />
    </div>
  );
}
