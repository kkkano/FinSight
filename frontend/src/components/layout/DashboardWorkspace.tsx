import { useEffect, useState } from 'react';
import type { MouseEvent } from 'react';
import { ChevronUp, Loader2 } from 'lucide-react';
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
  const latestRunStatus = useExecutionStore((state) => {
    const run = state.activeRuns[state.activeRuns.length - 1]
      ?? state.recentRuns[0]
      ?? null;
    return run?.status ?? null;
  });

  const [execCollapsed, setExecCollapsed] = useState(true);

  // 执行中自动展开，完成后自动折叠
  useEffect(() => {
    if (latestRunStatus === 'running' || latestRunStatus === 'interrupted') {
      setExecCollapsed(false);
    } else if (latestRunStatus === 'done' || latestRunStatus === 'error') {
      setExecCollapsed(true);
    }
  }, [latestRunStatus]);

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
          ) : latestRunId ? (
            execCollapsed ? (
              <button
                type="button"
                onClick={() => setExecCollapsed(false)}
                className="w-full flex items-center justify-between gap-2 px-3 py-2 rounded-xl border border-fin-border bg-fin-card text-xs text-fin-muted hover:bg-fin-hover transition-colors"
              >
                <span className="flex items-center gap-1.5">
                  {latestRunStatus === 'running' && <Loader2 size={12} className="animate-spin text-blue-300" />}
                  执行追踪（已折叠）
                </span>
                <ChevronUp size={14} />
              </button>
            ) : (
              <ExecutionPanel
                runId={latestRunId}
                mode={traceViewMode === 'expert' ? 'expert' : 'user'}
                collapsible
                onCollapse={() => setExecCollapsed(true)}
              />
            )
          ) : null}
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
