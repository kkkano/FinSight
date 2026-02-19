import type { MouseEvent } from 'react';
import { AgentLogPanel } from '../agent-log';
import { ExecutionPanel } from '../execution/ExecutionPanel';
import { Dashboard } from '../../pages/Dashboard';
import { useExecutionStore } from '../../store/executionStore';
import { useStore } from '../../store/useStore';
import { ContextPanelShell } from './ContextPanelShell';

type DashboardWorkspaceProps = {
  isMobile: boolean;
  symbol: string | null;
  onBackToChat: () => void;
  onSymbolChange: (symbol: string) => void;
  onGoWorkbench: (symbol: string) => void;
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

export function DashboardWorkspace({
  isMobile,
  symbol,
  onBackToChat,
  onSymbolChange,
  onGoWorkbench,
  contextPanel,
}: DashboardWorkspaceProps) {
  const traceViewMode = useStore((state) => state.traceViewMode);
  const latestRunId = useExecutionStore((state) => (
    state.activeRuns[state.activeRuns.length - 1]?.runId
      ?? state.recentRuns[0]?.runId
      ?? null
  ));

  return (
    <div className="h-full flex-1 min-w-0 flex min-h-0 overflow-hidden relative max-lg:flex-col">
      <div className="h-full flex-1 min-w-0 min-h-0 flex flex-col overflow-hidden">
        <Dashboard
          initialSymbol={symbol ?? undefined}
          onBackToChat={onBackToChat}
          onSymbolChange={onSymbolChange}
          onGoWorkbench={onGoWorkbench}
        />
        <div className="shrink-0 px-4 pb-4 max-lg:px-3 max-lg:pb-3">
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
