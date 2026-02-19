import { useMemo } from 'react';
import type { ReactNode } from 'react';
import { AlertTriangle, CheckCircle2, Loader2, PauseCircle, XCircle } from 'lucide-react';

import { useExecutionStore } from '../../store/executionStore';
import type { ExecutionRun } from '../../types/execution';
import { ExecutionStats } from './ExecutionStats';
import { GroupedTimeline } from './GroupedTimeline';
import { PipelineStageBar } from './PipelineStageBar';

type ExecutionPanelMode = 'user' | 'expert';

type ExecutionPanelProps = {
  runId?: string | null;
  mode?: ExecutionPanelMode;
  compact?: boolean;
  className?: string;
};

function resolveStatus(run: ExecutionRun): { icon: ReactNode; text: string; className: string } {
  if (run.status === 'running') {
    return {
      icon: <Loader2 size={14} className="animate-spin" />,
      text: '执行中',
      className: 'text-blue-300',
    };
  }
  if (run.status === 'done') {
    return {
      icon: <CheckCircle2 size={14} />,
      text: '已完成',
      className: 'text-emerald-300',
    };
  }
  if (run.status === 'error') {
    return {
      icon: <AlertTriangle size={14} />,
      text: '执行失败',
      className: 'text-red-300',
    };
  }
  if (run.status === 'interrupted') {
    return {
      icon: <PauseCircle size={14} />,
      text: '等待确认',
      className: 'text-amber-300',
    };
  }
  return {
    icon: <XCircle size={14} />,
    text: '已取消',
    className: 'text-fin-muted',
  };
}

function renderPlanSummary(run: ExecutionRun) {
  const selected = run.selectedAgents?.length ?? 0;
  const skipped = run.skippedAgents?.length ?? 0;
  const steps = run.planSteps?.length ?? 0;
  if (!selected && !skipped && !steps) return null;

  return (
    <div className="rounded-lg border border-fin-border bg-fin-bg/20 px-3 py-2 text-2xs">
      <div className="text-fin-text font-medium">计划摘要</div>
      <div className="mt-1 text-fin-muted flex flex-wrap items-center gap-3">
        <span>步骤：{steps}</span>
        <span>已选 Agent：{selected}</span>
        <span>跳过 Agent：{skipped}</span>
        {run.hasParallelPlan && <span className="text-fin-warning">并行执行</span>}
      </div>
      {run.reasoningBrief && (
        <div className="mt-2 text-fin-text/80 leading-relaxed">{run.reasoningBrief}</div>
      )}
    </div>
  );
}

function renderDecisionNotes(run: ExecutionRun) {
  const notes = run.decisionNotes ?? [];
  if (!notes.length) return null;
  return (
    <div className="rounded-lg border border-fin-border bg-fin-bg/20">
      <div className="px-3 py-2 border-b border-fin-border/60 text-xs text-fin-text-secondary">
        决策说明
      </div>
      <div className="max-h-52 overflow-y-auto divide-y divide-fin-border/40">
        {notes.slice(-8).reverse().map((note) => (
          <div key={note.id} className="px-3 py-2 text-2xs">
            <div className="text-fin-text font-medium">{note.title}</div>
            {note.reason && <div className="mt-1 text-fin-muted">原因：{note.reason}</div>}
            {note.impact && <div className="mt-1 text-fin-muted">影响：{note.impact}</div>}
            {note.nextStep && <div className="mt-1 text-fin-muted">下一步：{note.nextStep}</div>}
          </div>
        ))}
      </div>
    </div>
  );
}

export function ExecutionPanel({
  runId,
  mode = 'user',
  compact = false,
  className = '',
}: ExecutionPanelProps) {
  const run = useExecutionStore((state) => {
    if (runId) {
      return state.activeRuns.find((item) => item.runId === runId)
        ?? state.recentRuns.find((item) => item.runId === runId)
        ?? null;
    }
    return state.activeRuns[state.activeRuns.length - 1]
      ?? state.recentRuns[0]
      ?? null;
  });

  const statusInfo = useMemo(() => (run ? resolveStatus(run) : null), [run]);

  if (!run || !statusInfo) {
    return (
      <div className={`rounded-xl border border-fin-border bg-fin-card px-4 py-4 text-xs text-fin-muted ${className}`}>
        暂无可展示的执行追踪
      </div>
    );
  }

  const isExpert = mode === 'expert';

  return (
    <div className={`rounded-xl border border-fin-border bg-fin-card px-3 py-3 space-y-3 ${className}`}>
      <div className="flex items-center justify-between gap-2">
        <div className={`flex items-center gap-1.5 text-xs ${statusInfo.className}`}>
          {statusInfo.icon}
          {statusInfo.text}
        </div>
        <div className="text-2xs text-fin-muted truncate">
          {run.tickers.join(', ') || run.query}
        </div>
      </div>

      <PipelineStageBar
        stages={run.pipelineStages}
        currentStage={run.pipelineCurrentStage}
        compact={!isExpert}
      />

      <div className="rounded-lg border border-fin-border bg-fin-bg/20 px-3 py-2 text-xs text-fin-text/90">
        <div>{run.currentStep || '等待执行事件...'}</div>
        {run.status === 'running' && typeof run.etaSeconds === 'number' && run.etaSeconds > 0 && (
          <div className="mt-1 text-2xs text-fin-warning">预计剩余 ~{run.etaSeconds}s</div>
        )}
      </div>

      {run.status === 'interrupted' && (
        <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
          当前执行在等待用户确认，恢复后会继续后续步骤。
        </div>
      )}

      {isExpert && renderPlanSummary(run)}

      {isExpert && (
        <GroupedTimeline
          timeline={run.timeline}
          compact={compact}
          maxGroups={compact ? 6 : 10}
        />
      )}

      {isExpert && <ExecutionStats run={run} />}

      {isExpert && renderDecisionNotes(run)}
    </div>
  );
}

export default ExecutionPanel;
