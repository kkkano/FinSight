import type { ExecutionRun } from '../../types/execution';
import { extractWaterfallSteps } from './waterfallLayout';

export function summarizeExecutionMetrics(run: ExecutionRun) {
  const events = run.timeline;
  const steps = extractWaterfallSteps(events);
  const agents = Object.values(run.agentStatuses);
  const llmStarts = events.filter((event) => event.eventType === 'llm_start').length;
  const llmCalls = events.filter((event) => event.eventType === 'llm_call').length;
  const observedLlmCalls = Math.max(llmStarts, llmCalls);
  const toolSteps = steps.filter((step) => step.kind === 'tool');
  const observedToolCalls = Math.max(
    events.filter((event) => event.eventType === 'tool_start').length,
    events.filter((event) => event.eventType === 'tool_call').length,
  );
  const modelCallCount = run.tokenUsage?.llmCalls;

  return {
    // 没有调用事件或汇总时表示未采集，不能用 0 假装没有调用。
    llmCalls: typeof modelCallCount === 'number' && Number.isFinite(modelCallCount) && modelCallCount >= 0
      ? modelCallCount
      : observedLlmCalls || null,
    toolCalls: toolSteps.length || observedToolCalls || null,
    stepDone: steps.filter((step) => ['done', 'cached', 'skipped'].includes(step.status)).length,
    doneAgents: agents.filter((agent) => agent.status === 'done').length,
    errorAgents: agents.filter((agent) => agent.status === 'error').length,
    decisionNotes: run.decisionNotes?.length ?? 0,
    steps,
  };
}

export function formatExecutionDuration(startedAt: string, completedAt: string | null, now = Date.now()): string {
  const start = Date.parse(startedAt);
  const end = completedAt ? Date.parse(completedAt) : now;
  if (!Number.isFinite(start) || !Number.isFinite(end)) return '—';
  const seconds = Math.max(0, Math.round((end - start) / 1000));
  return seconds >= 60 ? `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒` : `${seconds} 秒`;
}
