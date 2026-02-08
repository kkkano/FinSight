import React from 'react';
import type { TraceViewMode } from '../../types';
import {
  formatConfidence,
  renderDecisionSummary,
  extractTraceSteps,
  renderTraceSteps,
  buildExpertSnapshot,
} from './thinkingUtils';

// ========== 详细结果格式化（开发视图） ==========
const formatDetailedResult = (result: any): React.ReactNode => {
  if (!result) return null;

  const items: React.ReactElement[] = [];
  const decisionSummary = renderDecisionSummary(result);
  if (decisionSummary) {
    items.push(<div key="decision-summary">{decisionSummary}</div>);
  }

  // 意图分类信息
  if (result.intent) {
    items.push(
      <div key="intent" className="flex items-center gap-2 py-1">
        <span className="text-fin-muted">意图:</span>
        <span className="px-2 py-0.5 bg-fin-primary/20 text-fin-primary rounded text-xs font-medium">
          {result.intent}
        </span>
      </div>
    );
  }

  // 分类方法
  if (result.method) {
    items.push(
      <div key="method" className="flex items-center gap-2 py-1">
        <span className="text-fin-muted">分类方法:</span>
        <span className="text-fin-text">{result.method}</span>
      </div>
    );
  }

  // 置信度
  if (result.confidence !== undefined) {
    items.push(
      <div key="confidence" className="flex items-center gap-2 py-1">
        <span className="text-fin-muted">置信度:</span>
        {formatConfidence(result.confidence)}
        <div className="flex-1 h-1.5 bg-fin-border rounded-full overflow-hidden ml-2">
          <div
            className={`h-full rounded-full ${
              result.confidence >= 0.8 ? 'bg-green-400' :
              result.confidence >= 0.6 ? 'bg-yellow-400' : 'bg-red-400'
            }`}
            style={{ width: `${result.confidence * 100}%` }}
          />
        </div>
      </div>
    );
  }

  // Agent 选择理由（policy_gate）
  if (result.agent_selection && typeof result.agent_selection === 'object') {
    const selection = result.agent_selection as {
      selected?: string[];
      required?: string[];
      scored?: Array<{ agent?: string; score?: number; reasons?: string[] }>;
    };
    const selected = Array.isArray(selection.selected) ? selection.selected : [];
    const required = Array.isArray(selection.required) ? selection.required : [];
    const scored = Array.isArray(selection.scored) ? selection.scored : [];

    if (selected.length > 0 || scored.length > 0) {
      items.push(
        <div key="agent-selection" className="py-1">
          <div className="text-fin-muted mb-1">Agent 选择依据:</div>
          {selected.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mb-2">
              {selected.map((name) => (
                <span key={name} className="px-2 py-0.5 rounded bg-blue-500/20 text-blue-300 text-[11px]">
                  {name}
                  {required.includes(name) ? ' \u00b7 required' : ''}
                </span>
              ))}
            </div>
          )}
          {scored.length > 0 && (
            <div className="space-y-1">
              {scored.map((row, idx) => (
                <div key={`${row.agent || 'agent'}-${idx}`} className="text-[11px] text-fin-text/90">
                  <div className="font-medium">
                    {row.agent || `agent_${idx + 1}`}
                    {typeof row.score === 'number' ? ` (${row.score.toFixed(2)})` : ''}
                  </div>
                  {Array.isArray(row.reasons) && row.reasons.length > 0 && (
                    <div className="text-fin-muted pl-2">{'\u2022'} {row.reasons.join(' \u00b7 ')}</div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      );
    }
  }

  // 选择的 Agent
  if (result.agent || result.agent_name) {
    items.push(
      <div key="agent" className="flex items-center gap-2 py-1">
        <span className="text-fin-muted">执行Agent:</span>
        <span className="px-2 py-0.5 bg-blue-500/20 text-blue-400 rounded text-xs font-medium">
          {result.agent || result.agent_name}
        </span>
      </div>
    );
  }

  // 工具调用
  if (result.tool || result.tools) {
    const tools = result.tools || [result.tool];
    items.push(
      <div key="tools" className="flex items-center gap-2 py-1 flex-wrap">
        <span className="text-fin-muted">工具:</span>
        {tools.map((tool: string, i: number) => (
          <span key={i} className="px-2 py-0.5 bg-yellow-500/20 text-yellow-400 rounded text-xs font-medium">
            {tool}
          </span>
        ))}
      </div>
    );
  }

  // 推理过程
  if (result.reasoning) {
    items.push(
      <div key="reasoning" className="py-1">
        <span className="text-fin-muted">推理:</span>
        <p className="text-fin-text/80 text-xs mt-1 pl-2 border-l-2 border-fin-primary/30">
          {result.reasoning}
        </p>
      </div>
    );
  }

  // 数据源
  if (result.data_sources || result.sources) {
    const sources = result.data_sources || result.sources;
    items.push(
      <div key="sources" className="flex items-center gap-2 py-1 flex-wrap">
        <span className="text-fin-muted">数据源:</span>
        {sources.map((src: string, i: number) => (
          <span key={i} className="px-2 py-0.5 bg-fin-panel text-fin-muted rounded text-xs">
            {src}
          </span>
        ))}
      </div>
    );
  }

  // 错误信息
  if (result.error || result.errors) {
    const errors = result.errors || [result.error];
    items.push(
      <div key="errors" className="py-1">
        <span className="text-red-400">错误:</span>
        {errors.map((err: string, i: number) => (
          <p key={i} className="text-red-400/80 text-xs mt-1">{err}</p>
        ))}
      </div>
    );
  }

  const traceBlocks = [
    { label: 'Trace', value: result.trace },
    { label: 'Trace Steps', value: result.trace_steps },
    { label: 'Steps', value: result.steps },
  ];

  traceBlocks.forEach((block) => {
    const steps = extractTraceSteps(block.value);
    if (steps.length === 0) return;
    items.push(
      <div key={`trace-${block.label}`} className="pt-1">
        <div className="text-2xs text-fin-muted uppercase mb-1">{block.label}</div>
        {renderTraceSteps(steps)}
      </div>
    );
  });

  if (items.length === 0) {
    // 如果没有特定字段，显示原始 JSON
    return (
      <pre className="mt-1 text-xs bg-fin-bg p-2 rounded overflow-x-auto max-h-32">
        {JSON.stringify(result, null, 2)}
      </pre>
    );
  }

  return <div className="mt-1 space-y-0.5">{items}</div>;
};

// ========== 步骤详情组件 ==========

interface ThinkingStepDetailProps {
  result: any;
  traceViewMode: TraceViewMode;
}

/**
 * ThinkingStepDetail - 单个步骤的展开详情
 * 包含工具调用详情、JSON 数据块、决策摘要等
 */
export const ThinkingStepDetail: React.FC<ThinkingStepDetailProps> = ({
  result,
  traceViewMode,
}) => {
  return (
    <div className="px-3 pb-2 pt-1 border-t border-fin-border/30 bg-fin-bg/30">
      {traceViewMode === 'user' ? (
        <div className="space-y-2">
          {renderDecisionSummary(result) || (
            <div className="text-[11px] text-fin-muted">暂无更多可解释信息。</div>
          )}
        </div>
      ) : traceViewMode === 'expert' ? (
        <div className="space-y-2">
          {renderDecisionSummary(result)}
          {(() => {
            const expertSnapshot = buildExpertSnapshot(result);
            if (Object.keys(expertSnapshot).length === 0) {
              return <div className="text-[11px] text-fin-muted">暂无专家层详情。</div>;
            }
            return (
              <pre className="text-2xs bg-fin-panel/60 p-2 rounded max-h-40 overflow-auto">
                {JSON.stringify(expertSnapshot, null, 2)}
              </pre>
            );
          })()}
        </div>
      ) : (
        formatDetailedResult(result)
      )}
    </div>
  );
};
