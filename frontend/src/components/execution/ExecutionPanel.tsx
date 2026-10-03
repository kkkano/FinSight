import { useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { AlertTriangle, CheckCircle2, ChevronDown, Clock3, Loader2, Square, XCircle } from 'lucide-react';

import { useExecutionStore } from '../../store/executionStore';
import type { ExecutionRun } from '../../types/execution';
import { formatDuration, waterfallStatusLabel } from './colorMaps';
import { formatExecutionDuration, summarizeExecutionMetrics } from './executionMetrics';
import { ExecutionStats } from './ExecutionStats';
import { GroupedTimeline } from './GroupedTimeline';
import { ParallelWaterfall } from './ParallelWaterfall';
import { PipelineStageBar } from './PipelineStageBar';
import { executionSubjectLabel, isTimelineError, summarizeTimelineEvent } from './timelineUtils';

function CollapsibleDetails({ details }: { details: Record<string, unknown> }) {
  return (
    <details className="mt-2 text-xs text-t-text2">
      <summary className="cursor-pointer py-1">原始详情</summary>
      <pre className="mt-2 whitespace-pre-wrap break-all font-mono text-xs leading-relaxed">{JSON.stringify(details, null, 2)}</pre>
    </details>
  );
}

type ExecutionPanelProps = {
  runId?: string | null;
  compact?: boolean;
  collapsible?: boolean;
  onCollapse?: () => void;
  className?: string;
};

function resolveStatus(run: ExecutionRun): { icon: ReactNode; text: string; className: string } {
  if (run.status === 'running') return { icon: <Loader2 size={16} className="animate-spin" />, text: '执行中', className: 'text-t-info' };
  if (run.status === 'done') return { icon: <CheckCircle2 size={16} />, text: '已完成', className: 'text-emerald-600 dark:text-emerald-400' };
  if (run.status === 'error') return { icon: <AlertTriangle size={16} />, text: '执行失败', className: 'text-red-600 dark:text-red-400' };
  return { icon: <XCircle size={16} />, text: '已取消', className: 'text-t-text2' };
}

function PlanSummary({ run }: { run: ExecutionRun }) {
  if (!run.planSteps?.length && !run.selectedAgents?.length && !run.reasoningBrief) return null;
  return (
    <section className="border-t border-t-divider pt-4 text-sm">
      <h3 className="font-medium text-t-text">计划摘要</h3>
      <p className="mt-2 text-xs text-t-text2">
        {run.planSteps?.length ?? 0} 个步骤 · {run.selectedAgents?.length ?? 0} 个分析 Agent
        {run.hasParallelPlan ? ' · 并行执行' : ''}
      </p>
      {run.reasoningBrief && <p className="mt-2 break-words leading-relaxed text-t-text2">{run.reasoningBrief}</p>}
      {!!run.budgetPriority?.length && (
        <details className="mt-3 text-xs text-t-text2">
          <summary className="cursor-pointer py-1">预算优先级</summary>
          <ol className="mt-2 space-y-2">
            {run.budgetPriority.map((item) => (
              <li key={item.agent} className="flex flex-wrap justify-between gap-2">
                <span>{item.rank}. {executionSubjectLabel(item.agent)}</span>
                <span className="num">
                  {typeof item.estimatedEffort === 'number' ? `effort ${item.estimatedEffort}` : ''}
                  {typeof item.estimatedLatencyMs === 'number' ? ` · 约 ${formatDuration(item.estimatedLatencyMs)}` : ''}
                </span>
              </li>
            ))}
          </ol>
        </details>
      )}
    </section>
  );
}

function DecisionNotes({ run }: { run: ExecutionRun }) {
  if (!run.decisionNotes?.length) return null;
  return (
    <section className="border-t border-t-divider pt-4">
      <h3 className="text-sm font-medium text-t-text">决策说明</h3>
      <div className="mt-2 divide-y divide-t-divider">
        {run.decisionNotes.slice(-8).reverse().map((note) => (
          <div key={note.id} className="py-3 text-xs leading-relaxed text-t-text2">
            <p className="text-sm font-medium text-t-text">{note.title}</p>
            {note.code && <p className="mt-1 break-all font-mono">{note.code}</p>}
            {note.reason && <p className="mt-1">原因：{note.reason}</p>}
            {note.impact && <p className="mt-1">影响：{note.impact}</p>}
            {note.nextStep && <p className="mt-1">下一步：{note.nextStep}</p>}
            {note.details && Object.keys(note.details).length > 0 && <CollapsibleDetails details={note.details} />}
          </div>
        ))}
      </div>
    </section>
  );
}

export function ExecutionPanel({ runId, compact = false, collapsible = false, onCollapse, className = '' }: ExecutionPanelProps) {
  const run = useExecutionStore((state) => runId
    ? state.activeRuns.find((item) => item.runId === runId) ?? state.recentRuns.find((item) => item.runId === runId) ?? null
    : state.activeRuns.at(-1) ?? state.recentRuns[0] ?? null);
  const cancelExecution = useExecutionStore((state) => state.cancelExecution);
  const [now, setNow] = useState(Date.now);

  useEffect(() => {
    if (run?.status !== 'running') return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [run?.status]);

  const metrics = useMemo(() => run ? summarizeExecutionMetrics(run) : null, [run]);
  const errors = useMemo(() => {
    if (!run) return [];
    return [...new Set([
      run.error,
      ...Object.values(run.agentStatuses).filter((agent) => agent.status === 'error').map((agent) => agent.error || `${executionSubjectLabel(agent.name)}失败`),
      ...run.timeline.filter(isTimelineError).map(summarizeTimelineEvent),
    ].filter((message): message is string => !!message))];
  }, [run]);

  if (!run || !metrics) return <div className="py-10 text-center text-sm text-t-text2">开始研究后查看执行进度</div>;
  const statusInfo = resolveStatus(run);
  const slowest = metrics.steps.filter((step) => typeof step.durationMs === 'number').sort((a, b) => b.durationMs! - a.durationMs!)[0];
  const keySteps = [...new Map([
    ...metrics.steps.filter((step) => step.status === 'running' || step.status === 'error'),
    ...(slowest ? [slowest] : []),
    ...metrics.steps.slice().reverse(),
  ].map((step) => [step.stepId, step])).values()].slice(0, compact ? 4 : 6);
  const latestMessage = run.timeline.filter((event) => event.userMessage?.trim()).at(-1)?.userMessage;
  const currentMessage = run.status === 'running'
    ? latestMessage || run.currentStep || '正在准备研究'
    : run.status === 'done' ? '本轮研究已完成' : run.status === 'error' ? '本轮研究未完成' : '本轮研究已取消';

  return (
    <div className={`space-y-4 ${className}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className={`flex items-center gap-2 text-sm font-semibold ${statusInfo.className}`}>{statusInfo.icon}{statusInfo.text}</div>
        <div className="flex items-center gap-2">
          <span className="flex items-center gap-1.5 text-xs text-t-text2"><Clock3 size={14} />{formatExecutionDuration(run.startedAt, run.completedAt, now)}</span>
          {run.status === 'running' && (
            <button type="button" onClick={() => cancelExecution(run.runId)} className="flex h-8 w-8 items-center justify-center rounded-md text-t-text2 hover:bg-t-hover hover:text-t-text" title="取消执行" aria-label="取消执行"><Square size={14} /></button>
          )}
          {collapsible && onCollapse && (
            <button type="button" onClick={onCollapse} className="flex h-8 w-8 items-center justify-center rounded-md text-t-text2 hover:bg-t-hover" title="收起面板" aria-label="收起面板"><ChevronDown size={16} /></button>
          )}
        </div>
      </div>
      <p className="break-words text-sm font-medium text-t-text">{run.tickers.join(', ') || run.query}</p>
      <PipelineStageBar stages={run.pipelineStages} currentStage={run.pipelineCurrentStage} />
      <p className="break-words text-sm leading-relaxed text-t-text2">{currentMessage}</p>

      {errors.length > 0 && (
        <section className="border-l-2 border-red-400 pl-3" aria-label="执行异常">
          <h3 className="flex items-center gap-2 text-sm font-medium text-red-600 dark:text-red-400"><AlertTriangle size={16} />执行异常</h3>
          {errors.slice(0, 3).map((error) => <p key={error} className="mt-2 break-words text-xs leading-relaxed text-t-text2">{error}</p>)}
        </section>
      )}
      {run.fallbackReasons.length > 0 && (
        <p className="break-words border-l-2 border-t-warning pl-3 text-xs leading-relaxed text-t-warning">降级原因：{[...new Set(run.fallbackReasons)].join('；')}</p>
      )}

      <ExecutionStats run={run} />
      {keySteps.length > 0 && (
        <section className="border-t border-t-divider pt-4">
          <h3 className="text-sm font-medium text-t-text">关键步骤</h3>
          <ul className="mt-2 divide-y divide-t-divider">
            {keySteps.map((step) => (
              <li key={step.stepId} className="flex items-start justify-between gap-3 py-3">
                <div className="min-w-0">
                  <p className="break-words text-sm text-t-text" title={step.name}>{executionSubjectLabel(step.name)}</p>
                  <p className="mt-1 text-xs text-t-text2">{waterfallStatusLabel(step.status)}{step === slowest ? ' · 最耗时' : ''}</p>
                </div>
                <span className={`num shrink-0 text-sm ${step === slowest ? 'font-medium text-t-warning' : 'text-t-text2'}`}>{formatDuration(step.durationMs)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <details open={compact ? undefined : true} className="border-t border-t-divider pt-2" data-testid="execution-details">
        <summary className="cursor-pointer py-2 text-sm font-medium text-t-text">执行详情</summary>
        <div className="space-y-4 pt-2">
          <PlanSummary run={run} />
          <ParallelWaterfall timeline={run.timeline} compact={compact} />
          <GroupedTimeline timeline={run.timeline} compact={compact} maxGroups={compact ? 6 : 10} />
          <DecisionNotes run={run} />
        </div>
      </details>
    </div>
  );
}

export default ExecutionPanel;
