import { useEffect, useState } from 'react';
import type { MouseEvent } from 'react';
import { ChevronUp, Loader2 } from 'lucide-react';

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
  const latestRunStatus = useExecutionStore((state) => {
    const run = state.activeRuns[state.activeRuns.length - 1]
      ?? state.recentRuns[0]
      ?? null;
    return run?.status ?? null;
  });

  const [collapsed, setCollapsed] = useState(false);

  // 执行中自动展开面板
  useEffect(() => {
    if (latestRunStatus === 'running' || latestRunStatus === 'interrupted') {
      setCollapsed(false);
    }
  }, [latestRunStatus]);

  const hasRun = latestRunId !== null;
  const isDevTrace = traceViewMode === 'dev';

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

        {/* 执行追踪面板：无任务时隐藏，折叠时显示迷你状态栏 */}
        {hasRun && (
          <div className="shrink-0 px-5 pb-5 max-lg:px-3 max-lg:pb-3">
            {collapsed ? (
              <button
                type="button"
                onClick={() => setCollapsed(false)}
                className="w-full flex items-center justify-between gap-2 px-3 py-2 rounded-xl border border-fin-border bg-fin-card text-xs text-fin-muted hover:bg-fin-hover transition-colors"
              >
                <span className="flex items-center gap-1.5">
                  {latestRunStatus === 'running' && <Loader2 size={12} className="animate-spin text-blue-300" />}
                  执行追踪（已折叠）
                </span>
                <ChevronUp size={14} />
              </button>
            ) : isDevTrace ? (
              <AgentLogPanel />
            ) : (
              <ExecutionPanel
                runId={latestRunId}
                mode={traceViewMode === 'expert' ? 'expert' : 'user'}
                collapsible
                onCollapse={() => setCollapsed(true)}
              />
            )}
          </div>
        )}
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
