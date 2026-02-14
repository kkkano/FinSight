import React from 'react';
import { ChevronDown } from 'lucide-react';
import type { ThinkingStep, TraceViewMode } from '../../types';
import { ThinkingStepDetail } from './ThinkingStepDetail';
import {
  stageLabels,
  formatLangGraphStage,
  getStageIcon,
  formatConfidence,
} from './thinkingUtils';

interface ThinkingStepListProps {
  thinking: ThinkingStep[];
  expandedSteps: Set<number>;
  traceViewMode: TraceViewMode;
  onToggleStep: (index: number) => void;
}

/**
 * ThinkingStepList - 可折叠的步骤列表渲染组件
 * 负责渲染各阶段的图标、标签，以及展开/收起状态
 */
export const ThinkingStepList: React.FC<ThinkingStepListProps> = ({
  thinking,
  expandedSteps,
  traceViewMode,
  onToggleStep,
}) => {
  return (
    <div className="mt-2 space-y-2 max-h-96 overflow-y-auto">
      {thinking.map((step, index) => (
        <div
          key={index}
          className="text-xs bg-fin-panel/50 rounded-lg border border-fin-border/50 overflow-hidden"
        >
          {/* 步骤头部按钮 */}
          <button
            onClick={() => onToggleStep(index)}
            className="w-full p-2 flex items-start gap-2 hover:bg-fin-panel/80 transition-colors"
          >
            <span className="mt-0.5">{getStageIcon(step.stage)}</span>
            <div className="flex-1 min-w-0 text-left">
              <div className="font-medium text-fin-text flex items-center gap-2">
                {formatLangGraphStage(step.stage) || stageLabels[step.stage] || step.stage}
                {step.result?.confidence !== undefined && (
                  <span className="text-2xs px-1.5 py-0.5 bg-fin-bg rounded">
                    置信度: {formatConfidence(step.result.confidence)}
                  </span>
                )}
              </div>
              {step.message && (
                <div className="text-fin-muted mt-0.5 truncate">{step.message}</div>
              )}
            </div>
            <div className="flex items-center gap-2">
              <span className="text-fin-muted/50 text-2xs">
                {new Date(step.timestamp).toLocaleTimeString()}
              </span>
              {step.result && (
                <ChevronDown
                  size={12}
                  className={`text-fin-muted transition-transform ${expandedSteps.has(index) ? 'rotate-180' : ''}`}
                />
              )}
            </div>
          </button>

          {/* 展开的步骤详情 */}
          {step.result && expandedSteps.has(index) && (
            <ThinkingStepDetail
              result={step.result}
              traceViewMode={traceViewMode}
            />
          )}
        </div>
      ))}
    </div>
  );
};
