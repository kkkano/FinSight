import { useMemo } from 'react';

import type { ExecutionRun } from '../../types/execution';

type ExecutionStatsProps = {
  run: ExecutionRun;
};

function formatDurationMs(startedAt?: string, completedAt?: string | null): string {
  if (!startedAt) return '--';
  const start = Date.parse(startedAt);
  if (!Number.isFinite(start)) return '--';
  const end = completedAt ? Date.parse(completedAt) : Date.now();
  if (!Number.isFinite(end)) return '--';
  const seconds = Math.max(0, Math.round((end - start) / 1000));
  return `${seconds}s`;
}

export function ExecutionStats({ run }: ExecutionStatsProps) {
  const stats = useMemo(() => {
    const events = run.timeline || [];
    const agentStatuses = Object.values(run.agentStatuses || {});
    const doneAgents = agentStatuses.filter((agent) => agent.status === 'done').length;
    const errorAgents = agentStatuses.filter((agent) => agent.status === 'error').length;

    const llmCalls = events.filter((event) => event.eventType === 'llm_start' || event.eventType === 'llm_call').length;
    const toolCalls = events.filter((event) => event.eventType === 'tool_start' || event.eventType === 'tool_call').length;
    const stepDone = events.filter((event) => event.eventType === 'step_done').length;
    const decisionNotes = run.decisionNotes?.length ?? 0;

    return {
      llmCalls,
      toolCalls,
      stepDone,
      doneAgents,
      errorAgents,
      decisionNotes,
    };
  }, [run]);

  return (
    <div className="rounded-lg border border-fin-border bg-fin-bg/20 px-3 py-2">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-2xs">
        <div className="text-fin-muted">
          LLM 调用
          <div className="text-fin-text text-xs mt-0.5">{stats.llmCalls}</div>
        </div>
        <div className="text-fin-muted">
          工具调用
          <div className="text-fin-text text-xs mt-0.5">{stats.toolCalls}</div>
        </div>
        <div className="text-fin-muted">
          已完成步骤
          <div className="text-fin-text text-xs mt-0.5">{stats.stepDone}</div>
        </div>
        <div className="text-fin-muted">
          执行耗时
          <div className="text-fin-text text-xs mt-0.5">{formatDurationMs(run.startedAt, run.completedAt)}</div>
        </div>
      </div>
      <div className="mt-2 pt-2 border-t border-fin-border/60 text-2xs text-fin-muted flex flex-wrap items-center gap-3">
        <span>Agent 成功：{stats.doneAgents}</span>
        <span>Agent 异常：{stats.errorAgents}</span>
        <span>决策说明：{stats.decisionNotes}</span>
        {typeof run.etaSeconds === 'number' && run.etaSeconds > 0 && run.status === 'running' && (
          <span className="text-fin-warning">预计剩余：~{run.etaSeconds}s</span>
        )}
      </div>
    </div>
  );
}

export default ExecutionStats;

