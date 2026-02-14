import React from 'react';
import { Brain, Cpu, Target, Wrench, Sparkles, AlertCircle } from 'lucide-react';

// ========== 阶段标签映射 ==========
export const stageLabels: Record<string, string> = {
  reference_resolution: '理解上下文',
  intent_classification: '意图分类',
  agent_gate: 'Agent 闸门',
  data_collection: '数据收集',
  processing: '处理中',
  complete: '完成',
  tool_call: '工具调用',
  llm_call: 'LLM 推理',
  error: '错误',
  // Agent 进度事件
  supervisor_start: '🚀 多Agent分析启动',
  agent_start: '⏳ Agent 分析中',
  agent_done: '✅ Agent 完成',
  agent_error: '❌ Agent 失败',
  forum_start: '🔄 综合分析中',
  forum_done: '📊 综合完成',
  // 新增详细阶段
  classifying: '🔍 分析问题意图',
  classified: '🎯 意图识别完成',
  agent_selected: '🤖 选择专家Agent',
  tool_selected: '🔧 选择工具',
  reasoning: '💭 推理思考中',
  // LangGraph streaming
  langgraph_start: '🔗 LangGraph 启动',
  executor_step_start: '⚙️ 执行步骤开始',
  executor_step_done: '✅ 执行步骤完成',
  executor_step_error: '❌ 执行步骤失败',
  llm_call_start: '🧠 LLM 调用开始',
  llm_call_done: '🧠 LLM 调用完成',
  llm_call_error: '🧠 LLM 调用失败',
};

// ========== LangGraph 阶段格式化 ==========
export const formatLangGraphStage = (stage: string) => {
  if (!stage.startsWith('langgraph_')) return null;
  if (stage === 'langgraph_start') return stageLabels.langgraph_start;

  const suffix = stage.endsWith('_start') ? 'start' : stage.endsWith('_done') ? 'done' : null;
  if (!suffix) return null;

  const node = stage
    .replace(/^langgraph_/, '')
    .replace(/_(start|done)$/, '');
  return suffix === 'start'
    ? `▶️ LangGraph 节点开始：${node}`
    : `✅ LangGraph 节点完成：${node}`;
};

// ========== 阶段图标选择 ==========
export const getStageIcon = (stage: string) => {
  if (stage.includes('complete') || stage.includes('done') || stage.includes('classified')) return <Target size={14} className="text-green-400" />;
  if (stage.includes('error')) return <AlertCircle size={14} className="text-red-400" />;
  if (stage.includes('agent') || stage.includes('supervisor')) return <Cpu size={14} className="text-blue-400" />;
  if (stage.includes('tool')) return <Wrench size={14} className="text-yellow-400" />;
  if (stage.includes('reasoning') || stage.includes('llm')) return <Sparkles size={14} className="text-purple-400" />;
  if (stage.includes('start') || stage.includes('processing') || stage.includes('collection')) return <Brain size={14} className="text-fin-primary animate-pulse" />;
  return <Brain size={14} className="text-fin-muted" />;
};

// ========== 置信度格式化 ==========
export const formatConfidence = (confidence: number) => {
  const percent = Math.round(confidence * 100);
  const color = percent >= 80 ? 'text-green-400' : percent >= 60 ? 'text-yellow-400' : 'text-red-400';
  return <span className={color}>{percent}%</span>;
};

// ========== Trace 辅助函数 ==========
export const formatTraceTimestamp = (value?: string) => {
  if (!value) return '';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return '';
  return parsed.toLocaleTimeString();
};

export const getTraceLabel = (step: any, index: number) =>
  step?.stage || step?.state || step?.name || step?.agent || step?.tool || `Step ${index + 1}`;

export const getTraceSummary = (step: any) =>
  step?.message || step?.summary || step?.detail || step?.reasoning || step?.status || '';

// ========== 决策摘要渲染 ==========
export const renderDecisionSummary = (result: any): React.ReactNode => {
  if (!result || typeof result !== 'object') return null;

  const lines: string[] = [];
  if (typeof result.decision_type === 'string' && result.decision_type) {
    lines.push(`决策类型: ${result.decision_type}`);
  }
  if (typeof result.summary === 'string' && result.summary) {
    lines.push(`摘要: ${result.summary}`);
  }
  if (typeof result.input_state === 'string' && result.input_state) {
    lines.push(`输入状态: ${result.input_state}`);
  }
  if (Array.isArray(result.input_sources) && result.input_sources.length > 0) {
    lines.push(`输入来源: ${result.input_sources.join(', ')}`);
  }
  if (typeof result.decision_summary === 'string' && result.decision_summary) {
    lines.push(`决策: ${result.decision_summary}`);
  }
  if (typeof result.selection_summary === 'string' && result.selection_summary) {
    lines.push(`选择: ${result.selection_summary}`);
  }
  if (typeof result.status_reason === 'string' && result.status_reason) {
    lines.push(`状态原因: ${result.status_reason}`);
  }

  if (lines.length === 0) return null;
  return (
    <div className="mb-2 text-[11px] text-fin-text bg-fin-panel/40 border border-fin-border/40 rounded px-2 py-1.5">
      {lines.map((line, idx) => (
        <div key={`${idx}-${line}`}>{line}</div>
      ))}
    </div>
  );
};

// ========== Trace 步骤提取 ==========
export const extractTraceSteps = (value: any): any[] => {
  if (!value) return [];
  if (Array.isArray(value)) return value;
  if (Array.isArray(value.steps)) return value.steps;
  if (Array.isArray(value.trace_steps)) return value.trace_steps;
  if (Array.isArray(value.trace)) return value.trace;
  if (Array.isArray(value.children)) return value.children;
  return [];
};

// ========== Trace 步骤递归渲染 ==========
export const renderTraceSteps = (steps: any[], depth = 0, showPayload = true): React.ReactNode => {
  if (!steps || steps.length === 0) return null;
  return (
    <div className={`space-y-1 ${depth > 0 ? 'ml-3 border-l border-fin-border/40 pl-2' : ''}`}>
      {steps.map((step, index) => {
        const label = getTraceLabel(step, index);
        const summary = getTraceSummary(step);
        const timestamp = formatTraceTimestamp(step?.timestamp || step?.started_at || step?.completed_at);
        const nested = extractTraceSteps(step?.steps || step?.trace_steps || step?.trace || step?.children);
        const payload = step?.result || step?.data || step?.payload || step;
        const payloadIsEmptyObject = payload && typeof payload === 'object' && !Array.isArray(payload) && Object.keys(payload).length === 0;
        const shouldShowPayload = Boolean(showPayload && !payloadIsEmptyObject);
        return (
          <details key={`${depth}-${index}`} className="group rounded-md border border-fin-border/40 bg-fin-bg/40 px-2 py-1">
            <summary className="cursor-pointer list-none flex items-start gap-2 text-[11px] text-fin-text">
              <span className="mt-0.5">{getStageIcon(String(step?.stage || step?.state || step?.name || 'step'))}</span>
              <div className="flex-1 min-w-0">
                <div className="font-medium truncate">{label}</div>
                {summary && <div className="text-2xs text-fin-muted truncate">{summary}</div>}
              </div>
              {timestamp && <span className="text-2xs text-fin-muted">{timestamp}</span>}
            </summary>
            <div className="mt-2 space-y-2">
              {nested.length > 0 && renderTraceSteps(nested, depth + 1, showPayload)}
              {shouldShowPayload && (
                <pre className="text-2xs bg-fin-panel/60 p-2 rounded max-h-40 overflow-auto">
                  {JSON.stringify(payload, null, 2)}
                </pre>
              )}
            </div>
          </details>
        );
      })}
    </div>
  );
};

// ========== 专家视图候选字段 ==========
const EXPERT_CANDIDATE_KEYS = [
  'agent',
  'agent_name',
  'tools',
  'tool',
  'data_sources',
  'sources',
  'confidence',
  'status_reason',
  'selection_summary',
  'input_state',
  'input_sources',
  'fallback_reason',
];

// ========== 专家视图快照提取 ==========
export const buildExpertSnapshot = (result: any): Record<string, any> => {
  const snapshot: Record<string, any> = {};
  EXPERT_CANDIDATE_KEYS.forEach((key) => {
    const value = result?.[key];
    const hasValue =
      value !== undefined &&
      value !== null &&
      !(typeof value === 'string' && value.trim() === '') &&
      !(Array.isArray(value) && value.length === 0) &&
      !(typeof value === 'object' && !Array.isArray(value) && Object.keys(value).length === 0);
    if (hasValue) {
      snapshot[key] = value;
    }
  });
  return snapshot;
};
