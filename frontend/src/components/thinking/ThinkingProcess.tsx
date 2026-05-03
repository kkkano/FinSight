import { useState, useMemo } from 'react';
import { Brain, ChevronDown, ChevronUp, Sparkles } from 'lucide-react';
import type { ThinkingStep, TraceViewMode } from '../../types';
import React from 'react';
import { useStore } from '../../store/useStore';
import { ThinkingStepList } from './ThinkingStepList';
import { ThinkingUserView } from './ThinkingUserView';

const VIEW_MODE_LABELS: Record<TraceViewMode, string> = {
  user: '用户视图',
  expert: '专家视图',
  dev: '开发视图',
};

const VIEW_MODE_ORDER: TraceViewMode[] = ['user', 'expert', 'dev'];

const cycleViewMode = (mode: TraceViewMode): TraceViewMode => {
  const idx = VIEW_MODE_ORDER.indexOf(mode);
  return VIEW_MODE_ORDER[(idx + 1) % VIEW_MODE_ORDER.length];
};

// 重新导出类型供子组件使用
export type { TraceViewMode } from '../../types';

interface ThinkingProcessProps {
  thinking: ThinkingStep[];
}

/**
 * ThinkingProcess - 主容器组件
 * 用户模式：展示 ThinkingUserView（4 阶段 + Agent 卡片）
 * 专家/开发模式：展示 ThinkingStepList（完整 trace）
 */
export const ThinkingProcess: React.FC<ThinkingProcessProps> = ({ thinking }) => {
  const traceViewMode = useStore((state) => state.traceViewMode);
  const setTraceViewMode = useStore((state) => state.setTraceViewMode);
  const isUserMode = traceViewMode === 'user';

  // 用户模式默认收起，开发/专家模式默认展开
  const [isExpanded, setIsExpanded] = useState(!isUserMode);
  const [expandedSteps, setExpandedSteps] = useState<Set<number>>(new Set([0]));

  // 判断分析是否全部完成（用于用户模式标题显示）
  const isAllDone = useMemo(() => {
    if (!thinking?.length) return false;
    return thinking.some(
      (s) => s.stage === 'langgraph_render_done' || s.stage === 'langgraph_save_memory_done',
    );
  }, [thinking]);

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

  // T4：视图模式 chip 改为按钮 —— 单击循环切换 user → expert → dev
  const handleCycleViewMode = (e: React.MouseEvent) => {
    e.stopPropagation();
    const next = cycleViewMode(traceViewMode);
    setTraceViewMode(next);
    // 切到非用户视图自动展开，方便看 trace
    if (next !== 'user') setIsExpanded(true);
  };

  return (
    <div className="mt-3 border-t border-fin-border pt-3">
      {/* 整体展开/收起按钮 */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex items-center justify-between w-full text-xs text-fin-muted hover:text-fin-text transition-colors"
      >
        <div className="flex items-center gap-2">
          {isUserMode ? (
            <Sparkles size={14} className="text-emerald-400" />
          ) : (
            <Brain size={14} className="text-fin-primary" />
          )}
          <span className="font-medium">
            {isUserMode ? '分析过程' : 'Agent Trace'}
          </span>
          {isUserMode ? (
            <span className="text-fin-muted">
              {isAllDone ? '✓ 已完成' : '分析中...'}
            </span>
          ) : (
            <span className="text-fin-muted">({thinking.length} 步骤)</span>
          )}
          {/* 可点击的视图模式切换 chip */}
          <span
            role="button"
            tabIndex={0}
            onClick={handleCycleViewMode}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                handleCycleViewMode(e as unknown as React.MouseEvent);
              }
            }}
            title={`点击切换视图（当前：${VIEW_MODE_LABELS[traceViewMode]}）`}
            className="text-2xs px-1.5 py-0.5 rounded bg-fin-panel border border-fin-border/60 text-fin-muted hover:bg-fin-primary/10 hover:border-fin-primary/40 hover:text-fin-primary cursor-pointer transition-colors select-none"
          >
            {VIEW_MODE_LABELS[traceViewMode]}
          </span>
        </div>
        {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      </button>

      {/* 内容区域：根据模式切换渲染 */}
      {isExpanded && (
        isUserMode ? (
          <ThinkingUserView thinking={thinking} />
        ) : (
          <ThinkingStepList
            thinking={thinking}
            expandedSteps={expandedSteps}
            traceViewMode={traceViewMode}
            onToggleStep={toggleStep}
          />
        )
      )}
    </div>
  );
};
