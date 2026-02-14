import { useState } from 'react';
import { Brain, ChevronDown, ChevronUp } from 'lucide-react';
import type { ThinkingStep } from '../../types';
import React from 'react';
import { useStore } from '../../store/useStore';
import { ThinkingStepList } from './ThinkingStepList';

// 重新导出类型供子组件使用
export type { TraceViewMode } from '../../types';

interface ThinkingProcessProps {
  thinking: ThinkingStep[];
}

/**
 * ThinkingProcess - 主容器组件
 * 负责编排子组件、管理整体展开/收起状态和步骤展开状态
 */
export const ThinkingProcess: React.FC<ThinkingProcessProps> = ({ thinking }) => {
  const [isExpanded, setIsExpanded] = useState(true); // 默认展开
  const [expandedSteps, setExpandedSteps] = useState<Set<number>>(new Set([0])); // 默认展开第一个
  const traceViewMode = useStore((state) => state.traceViewMode);

  if (!thinking?.length) {
    return null;
  }

  // 切换单个步骤的展开/收起（不可变模式）
  const toggleStep = (index: number) => {
    const newExpanded = new Set(expandedSteps);
    if (newExpanded.has(index)) {
      newExpanded.delete(index);
    } else {
      newExpanded.add(index);
    }
    setExpandedSteps(newExpanded);
  };

  return (
    <div className="mt-3 border-t border-fin-border pt-3">
      {/* 整体展开/收起按钮 */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex items-center justify-between w-full text-xs text-fin-muted hover:text-fin-text transition-colors"
      >
        <div className="flex items-center gap-2">
          <Brain size={14} className="text-fin-primary" />
          <span className="font-medium">Agent Trace</span>
          <span className="text-fin-muted">({thinking.length} 步骤)</span>
          <span className="text-2xs px-1.5 py-0.5 rounded bg-fin-panel border border-fin-border/60 text-fin-muted">
            {traceViewMode === 'user' ? '用户视图' : traceViewMode === 'expert' ? '专家视图' : '开发视图'}
          </span>
        </div>
        {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      </button>

      {/* 步骤列表 */}
      {isExpanded && (
        <ThinkingStepList
          thinking={thinking}
          expandedSteps={expandedSteps}
          traceViewMode={traceViewMode}
          onToggleStep={toggleStep}
        />
      )}
    </div>
  );
};
