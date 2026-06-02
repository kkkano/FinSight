import React from 'react';
import { useExecutionStore } from '../store/executionStore';
import { PipelineStageBar } from './execution/PipelineStageBar';
import { AgentProgressList } from './execution/AgentProgressList';

/**
 * ResearchCard — 把「研究过程」（执行管线 stepper + Agent 网格）嵌进 AI 回复卡顶部，
 * 让对话里的 AI 回复呈现「投研研究卡」的骨架。
 *
 * 数据来自 execution store 的当前/最近 run（执行中实时）。
 * ③评分环 / ④指标网格 待后端补结构化字段（scoring/metrics）后再接入，避免空壳返工。
 */
export const ResearchCard: React.FC = () => {
  const run = useExecutionStore(
    (s) => s.activeRuns[s.activeRuns.length - 1] ?? s.recentRuns[0] ?? null,
  );
  if (!run) return null;

  const stages = run.pipelineStages;
  const agents = run.agentStatuses;
  const hasStages = Boolean(stages && Object.keys(stages).length > 0);
  const hasAgents = Boolean(agents && Object.keys(agents).length > 0);
  if (!hasStages && !hasAgents) return null;

  return (
    <div className="mb-3 rounded-xl border border-fin-border bg-fin-bg/40 p-3 space-y-3">
      <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-fin-muted">
        研究过程 · Research Pipeline
      </div>
      {hasStages && (
        <PipelineStageBar stages={stages} currentStage={run.pipelineCurrentStage} compact />
      )}
      {hasAgents && <AgentProgressList agentStatuses={agents!} />}
    </div>
  );
};
