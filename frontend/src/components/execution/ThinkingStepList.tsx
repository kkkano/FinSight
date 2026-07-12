import React from 'react';
import { ChevronDown } from 'lucide-react';
import type { ThinkingStep, TraceViewMode } from '../../types';
import { ThinkingStepDetail } from './ThinkingStepDetail';
import {
  stageLabels,
  formatLangGraphStage,
  getStageTone,
  formatConfidence,
} from './thinkingUtils';

interface ThinkingStepListProps {
  thinking: ThinkingStep[];
  expandedSteps: Set<number>;
  traceViewMode: TraceViewMode;
  onToggleStep: (index: number) => void;
}

/**
 * ThinkingStepList — 专家/开发视图的执行时间线（trace timeline）。
 *
 * 设计：抛弃「每步一个等大白卡片」的廉价堆叠，改为连续时间线 ——
 *   - 左侧贯穿竖轴（fin-primary → cyan 渐变）
 *   - 每步一个语义色节点圆点（plan/tool/agent/done/error 各异）
 *   - 紧凑单行：图标 + 阶段名 + 摘要 + 时间，hover 微亮
 *   - 可点击展开 ThinkingStepDetail
 * 与 ThinkingUserView 的时间轴语言保持同构。
 */
export const ThinkingStepList: React.FC<ThinkingStepListProps> = ({
  thinking,
  expandedSteps,
  traceViewMode,
  onToggleStep,
}) => {
  return (
    <div className="relative mt-2 pl-5 max-h-96 overflow-y-auto">
      {/* 贯穿竖轴 —— FinSight 主题色渐变 */}
      <div
        aria-hidden
        className="absolute left-[7px] top-1 bottom-1 w-[2px] rounded-full bg-gradient-to-b from-fin-primary via-cyan-400/50 to-fin-primary/10 opacity-50"
      />

      {thinking.map((step, index) => {
        const tone = getStageTone(step.stage);
        const Icon = tone.Icon;
        const isExpanded = expandedSteps.has(index);
        const canExpand = Boolean(step.result);
        const label =
          formatLangGraphStage(step.stage) || stageLabels[step.stage] || step.stage;

        return (
          <div key={index} className="relative pb-1.5 last:pb-0">
            {/* 节点圆点 */}
            <div
              className={`absolute -left-[18px] top-[6px] w-[14px] h-[14px] rounded-full border-2 flex items-center justify-center shrink-0 ${tone.dot}`}
            >
              <span className="w-1 h-1 rounded-full bg-current opacity-80" />
            </div>

            {/* 行 */}
            <button
              onClick={() => canExpand && onToggleStep(index)}
              disabled={!canExpand}
              className={`group w-full flex items-center gap-2 px-2 py-1 rounded-md text-xs text-left transition-colors ${
                canExpand ? 'cursor-pointer hover:bg-fin-hover/40' : 'cursor-default'
              }`}
            >
              <Icon size={13} className={`shrink-0 ${tone.icon}`} />
              <span className="font-medium text-fin-text shrink-0">{label}</span>
              {step.result?.confidence !== undefined && (
                <span className="text-2xs px-1.5 py-0.5 rounded bg-fin-bg/60 shrink-0">
                  {formatConfidence(step.result.confidence)}
                </span>
              )}
              {step.message ? (
                <span className="flex-1 min-w-0 truncate text-fin-muted">
                  {step.message}
                </span>
              ) : (
                <span className="flex-1" />
              )}
              <span className="text-fin-muted/40 text-2xs tabular-nums shrink-0">
                {new Date(step.timestamp).toLocaleTimeString()}
              </span>
              {canExpand && (
                <ChevronDown
                  size={12}
                  className={`text-fin-muted/60 shrink-0 transition-transform ${
                    isExpanded ? 'rotate-180' : ''
                  }`}
                />
              )}
            </button>

            {/* 展开的步骤详情 */}
            {canExpand && isExpanded && (
              <div className="ml-2 mt-1 mb-1 rounded-md border border-fin-border/40 bg-fin-panel/30 overflow-hidden animate-fade-in">
                <ThinkingStepDetail result={step.result} traceViewMode={traceViewMode} />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
};
