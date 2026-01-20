import { useState } from 'react';
import { Brain, ChevronDown, ChevronUp, Cpu, Target, Wrench, Sparkles, AlertCircle } from 'lucide-react';
import type { ThinkingStep } from '../types';
import React from 'react';

interface ThinkingProcessProps {
  thinking: ThinkingStep[];
}

const stageLabels: Record<string, string> = {
  reference_resolution: '理解上下文',
  intent_classification: '意图分类',
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
};

const getStageIcon = (stage: string) => {
  if (stage.includes('complete') || stage.includes('done') || stage.includes('classified')) return <Target size={14} className="text-green-400" />;
  if (stage.includes('error')) return <AlertCircle size={14} className="text-red-400" />;
  if (stage.includes('agent') || stage.includes('supervisor')) return <Cpu size={14} className="text-blue-400" />;
  if (stage.includes('tool')) return <Wrench size={14} className="text-yellow-400" />;
  if (stage.includes('reasoning') || stage.includes('llm')) return <Sparkles size={14} className="text-purple-400" />;
  if (stage.includes('start') || stage.includes('processing') || stage.includes('collection')) return <Brain size={14} className="text-fin-primary animate-pulse" />;
  return <Brain size={14} className="text-fin-muted" />;
};

// 格式化置信度显示
const formatConfidence = (confidence: number) => {
  const percent = Math.round(confidence * 100);
  const color = percent >= 80 ? 'text-green-400' : percent >= 60 ? 'text-yellow-400' : 'text-red-400';
  return <span className={color}>{percent}%</span>;
};

const formatTraceTimestamp = (value?: string) => {
  if (!value) return '';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return '';
  return parsed.toLocaleTimeString();
};

const getTraceLabel = (step: any, index: number) =>
  step?.stage || step?.state || step?.name || step?.agent || step?.tool || `Step ${index + 1}`;

const getTraceSummary = (step: any) =>
  step?.message || step?.summary || step?.detail || step?.reasoning || step?.status || '';

const extractTraceSteps = (value: any): any[] => {
  if (!value) return [];
  if (Array.isArray(value)) return value;
  if (Array.isArray(value.steps)) return value.steps;
  if (Array.isArray(value.trace_steps)) return value.trace_steps;
  if (Array.isArray(value.trace)) return value.trace;
  if (Array.isArray(value.children)) return value.children;
  return [];
};

const renderTraceSteps = (steps: any[], depth = 0): React.ReactNode => {
  if (!steps || steps.length === 0) return null;
  return (
    <div className={`space-y-1 ${depth > 0 ? 'ml-3 border-l border-fin-border/40 pl-2' : ''}`}>
      {steps.map((step, index) => {
        const label = getTraceLabel(step, index);
        const summary = getTraceSummary(step);
        const timestamp = formatTraceTimestamp(step?.timestamp || step?.started_at || step?.completed_at);
        const nested = extractTraceSteps(step?.steps || step?.trace_steps || step?.trace || step?.children);
        const payload = step?.result || step?.data || step?.payload || step;
        return (
          <details key={`${depth}-${index}`} className="group rounded-md border border-fin-border/40 bg-fin-bg/40 px-2 py-1">
            <summary className="cursor-pointer list-none flex items-start gap-2 text-[11px] text-fin-text">
              <span className="mt-0.5">{getStageIcon(String(step?.stage || step?.state || step?.name || 'step'))}</span>
              <div className="flex-1 min-w-0">
                <div className="font-medium truncate">{label}</div>
                {summary && <div className="text-[10px] text-fin-muted truncate">{summary}</div>}
              </div>
              {timestamp && <span className="text-[10px] text-fin-muted">{timestamp}</span>}
            </summary>
            <div className="mt-2 space-y-2">
              {nested.length > 0 && renderTraceSteps(nested, depth + 1)}
              <pre className="text-[10px] bg-fin-panel/60 p-2 rounded max-h-40 overflow-auto">
                {JSON.stringify(payload, null, 2)}
              </pre>
            </div>
          </details>
        );
      })}
    </div>
  );
};

// 格式化详细结果
const formatDetailedResult = (result: any): React.ReactNode => {
  if (!result) return null;

  const items: React.ReactElement[] = [];

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
        <div className="text-[10px] text-fin-muted uppercase mb-1">{block.label}</div>
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

export const ThinkingProcess: React.FC<ThinkingProcessProps> = ({ thinking }) => {
  const [isExpanded, setIsExpanded] = useState(true); // 默认展开
  const [expandedSteps, setExpandedSteps] = useState<Set<number>>(new Set([0])); // 默认展开第一个

  if (!thinking?.length) {
    return null;
  }

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
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex items-center justify-between w-full text-xs text-fin-muted hover:text-fin-text transition-colors"
      >
        <div className="flex items-center gap-2">
          <Brain size={14} className="text-fin-primary" />
          <span className="font-medium">Agent Trace</span>
          <span className="text-fin-muted">({thinking.length} 步骤)</span>
        </div>
        {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      </button>

      {isExpanded && (
        <div className="mt-2 space-y-2 max-h-96 overflow-y-auto">
          {thinking.map((step, index) => (
            <div
              key={index}
              className="text-xs bg-fin-panel/50 rounded-lg border border-fin-border/50 overflow-hidden"
            >
              <button
                onClick={() => toggleStep(index)}
                className="w-full p-2 flex items-start gap-2 hover:bg-fin-panel/80 transition-colors"
              >
                <span className="mt-0.5">{getStageIcon(step.stage)}</span>
                <div className="flex-1 min-w-0 text-left">
                  <div className="font-medium text-fin-text flex items-center gap-2">
                    {stageLabels[step.stage] || step.stage}
                    {step.result?.confidence !== undefined && (
                      <span className="text-[10px] px-1.5 py-0.5 bg-fin-bg rounded">
                        置信度: {formatConfidence(step.result.confidence)}
                      </span>
                    )}
                  </div>
                  {step.message && (
                    <div className="text-fin-muted mt-0.5 truncate">{step.message}</div>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-fin-muted/50 text-[10px]">
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

              {step.result && expandedSteps.has(index) && (
                <div className="px-3 pb-2 pt-1 border-t border-fin-border/30 bg-fin-bg/30">
                  {formatDetailedResult(step.result)}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
