import { useMemo } from 'react';

import type { ExecutionRun } from '../../types/execution';
import { formatExecutionDuration, summarizeExecutionMetrics } from './executionMetrics';

type ExecutionStatsProps = {
  run: ExecutionRun;
};

export function ExecutionStats({ run }: ExecutionStatsProps) {
  const stats = useMemo(() => summarizeExecutionMetrics(run), [run]);

  return (
    <div className="border-t border-t-divider pt-4">
      <dl className="grid grid-cols-2 gap-x-5 gap-y-4 text-xs" data-testid="execution-statistics">
        <div>
          <dt className="text-t-text2">LLM 调用</dt>
          <dd className="num mt-1 text-base font-medium text-t-text" title={stats.llmCalls === null ? '本轮未采集调用计数' : undefined}>{stats.llmCalls ?? '—'}</dd>
        </div>
        <div>
          <dt className="text-t-text2">工具步骤</dt>
          <dd className="num mt-1 text-base font-medium text-t-text" title={stats.toolCalls === null ? '本轮未采集工具步骤' : '含缓存命中及跳过的取数步骤'}>{stats.toolCalls ?? '—'}</dd>
        </div>
        <div>
          <dt className="text-t-text2">已完成步骤</dt>
          <dd className="num mt-1 text-base font-medium text-t-text">{stats.stepDone}</dd>
        </div>
        <div>
          <dt className="text-t-text2">执行耗时</dt>
          <dd className="num mt-1 text-base font-medium text-t-text">{formatExecutionDuration(run.startedAt, run.completedAt)}</dd>
        </div>
      </dl>
      <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-t-text2">
        <span>Agent 成功：{stats.doneAgents}</span>
        <span>Agent 异常：{stats.errorAgents}</span>
        <span>决策说明：{stats.decisionNotes}</span>
        {run.tokenUsage && run.tokenUsage.totalTokens > 0 && (
          <span className="text-t-text2">
            Token：{run.tokenUsage.totalTokens.toLocaleString()}
            <span>（↑{run.tokenUsage.promptTokens.toLocaleString()} ↓{run.tokenUsage.completionTokens.toLocaleString()}）</span>
          </span>
        )}
        {run.tokenUsage && run.tokenUsage.costUsd > 0 && (
          <span>成本：${run.tokenUsage.costUsd.toFixed(4)}</span>
        )}
        {typeof run.etaSeconds === 'number' && run.etaSeconds > 0 && run.status === 'running' && (
          <span className="text-t-warning">预计剩余：约 {run.etaSeconds} 秒</span>
        )}
      </div>
    </div>
  );
}

export default ExecutionStats;
