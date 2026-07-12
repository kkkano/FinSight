import React, { useMemo, useState } from 'react';
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Loader2,
  AlertTriangle,
  Clock,
  Search,
  Sparkles,
  FileSearch,
  FlaskConical,
  FileText,
  Zap,
} from 'lucide-react';
import type { ThinkingStep } from '../../types';
import {
  resolveUserMessage,
  getAgentDisplayName,
  normalizeAgentName,
} from '../../utils/userMessageMapper';

/* ===== Phase Configuration ===== */
const PHASES = [
  {
    id: 'understand',
    label: '理解意图',
    Icon: Search,
    nodes: [
      'build_initial_state', 'reset_turn', 'trim', 'summarize',
      'normalize', 'decide_output', 'understand_request', 'chat_respond',
      'resolve_subject', 'clarify', 'parse_operation',
    ],
    altStages: ['understanding', 'classifying', 'classified', 'intent_classification'],
    doneMarker: 'understand_request',
    altDoneStages: ['understanding', 'classified'],
  },
  {
    id: 'plan',
    label: '规划策略',
    Icon: Sparkles,
    nodes: ['policy_gate', 'planner', 'confirmation_gate'],
    altStages: ['agent_gate', 'agent_selected'],
    doneMarker: 'planner',
    altDoneStages: ['agent_selected'],
  },
  {
    id: 'retrieve',
    label: '检索证据',
    Icon: FileSearch,
    nodes: ['search', 'retrieve', 'rag', 'tool'],
    altStages: ['tool_start', 'tool_call', 'tool_end', 'data_source', 'api_call', 'cache_hit', 'cache_miss', 'cache_set'],
    doneMarker: 'execute_plan',
    altDoneStages: ['tool_end', 'data_source', 'api_call'],
  },
  {
    id: 'execute',
    label: '执行分析',
    Icon: FlaskConical,
    nodes: ['execute_plan'],
    altStages: ['processing', 'data_collection', 'agent_start', 'agent_done', 'executor_step_start', 'executor_step_done'],
    doneMarker: 'execute_plan',
    altDoneStages: ['complete'],
  },
  {
    id: 'synthesize',
    label: '整合报告',
    Icon: FileText,
    // ⚠️ 不能包含 'save_memory'：闲聊路径只走 chat_respond + save_memory，
    //    若 save_memory 命中本阶段会把 synthesize 误标为 active 且永远等不到 render_done。
    nodes: ['synthesize', 'render'],
    altStages: ['rendering', 'complete'],
    doneMarker: 'render',
    altDoneStages: ['complete'],
  },
] as const;

type PhaseStatus = 'pending' | 'active' | 'done';

interface ComputedPhase {
  id: string;
  label: string;
  Icon: typeof Search;
  status: PhaseStatus;
  steps: PhaseStep[];
  /** 阶段耗时（秒），无法计算时为 null */
  duration: number | null;
}

interface PhaseStep {
  stage: string;
  message: string;
  timestamp: string;
  isDone: boolean;
  agentName?: string;
}

interface AgentEntry {
  name: string;
  displayName: string;
  status: 'running' | 'done' | 'error';
  /** 0-100 置信度 */
  confidence?: number;
  /** 耗时（秒） */
  duration?: number | null;
}

/* ===== Helpers ===== */

function nodeOf(stage: string): string {
  return stage.replace(/^langgraph_/, '').replace(/_(start|done)$/, '');
}

function nodeMatches(node: string, pattern: string): boolean {
  return node === pattern || node.startsWith(pattern);
}

function formatTime(ts: string): string {
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch {
    return '';
  }
}

function getStepMessage(step: ThinkingStep): string {
  if (step.result?.userMessage && typeof step.result.userMessage === 'string') {
    return step.result.userMessage;
  }
  if ((step.eventType === 'trace' || step.result?.type === 'trace') && step.message) {
    return step.message;
  }
  if (step.stage === 'tool_start' || step.stage === 'tool_call' || step.stage === 'tool_end') {
    const toolName = step.result?.name || step.result?.tool || step.result?.tool_name || 'tool';
    if (step.stage === 'tool_start') return `调用工具：${toolName}`;
    if (step.stage === 'tool_end') return `工具完成：${toolName}`;
    return `工具请求：${toolName}`;
  }
  if (step.stage === 'api_call') {
    const method = step.result?.method || 'GET';
    const endpoint = step.result?.endpoint || step.result?.url || '';
    return `请求数据源：${method} ${endpoint}`.trim();
  }
  if (step.stage === 'data_source') {
    const source = step.result?.source || step.result?.provider || '数据源';
    const queryType = step.result?.query_type || step.result?.operation || '';
    return `读取${source}${queryType ? `：${queryType}` : ''}`;
  }
  const mapped = resolveUserMessage(step.stage);
  if (mapped) return mapped;
  if (step.message && typeof step.message === 'string') return step.message;
  return step.stage.replace(/^langgraph_/, '').replace(/_/g, ' ');
}

/* ===== Phase Computation ===== */

function computePhases(steps: ThinkingStep[]): ComputedPhase[] {
  const startedNodes = new Set<string>();
  const doneNodes = new Set<string>();
  const allStages = new Set<string>();
  /** node → 起止时间戳，用于估算 phase duration */
  const nodeTimings = new Map<string, { start?: number; end?: number }>();

  for (const s of steps) {
    allStages.add(s.stage);
    const ts = Date.parse(s.timestamp);
    if (s.stage.startsWith('langgraph_')) {
      const node = nodeOf(s.stage);
      if (s.stage.endsWith('_start')) {
        startedNodes.add(node);
        const t = nodeTimings.get(node) ?? {};
        if (Number.isFinite(ts)) t.start = ts;
        nodeTimings.set(node, t);
      }
      if (s.stage.endsWith('_done')) {
        doneNodes.add(node);
        const t = nodeTimings.get(node) ?? {};
        if (Number.isFinite(ts)) t.end = ts;
        nodeTimings.set(node, t);
      }
    }
  }

  const result: ComputedPhase[] = PHASES.map((phase) => {
    const hasLgStarted = phase.nodes.some((pattern) =>
      [...startedNodes].some((n) => nodeMatches(n, pattern)),
    );
    const lgMarkerDone = [...doneNodes].some((n) => nodeMatches(n, phase.doneMarker));

    const hasAltStarted = phase.altStages.some((s) => allStages.has(s));
    const altDone = phase.altDoneStages.some((s) => allStages.has(s));

    const hasStarted = hasLgStarted || hasAltStarted;
    const markerDone = lgMarkerDone || altDone;

    let status: PhaseStatus = 'pending';
    if (markerDone) status = 'done';
    else if (hasStarted) status = 'active';

    // 估算 phase duration —— 取 phase.nodes 中所有命中 node 的 (max end - min start)
    let phaseStart: number | undefined;
    let phaseEnd: number | undefined;
    for (const [node, t] of nodeTimings.entries()) {
      const matched = phase.nodes.some((pattern) => nodeMatches(node, pattern));
      if (!matched) continue;
      if (t.start !== undefined) phaseStart = phaseStart === undefined ? t.start : Math.min(phaseStart, t.start);
      if (t.end !== undefined) phaseEnd = phaseEnd === undefined ? t.end : Math.max(phaseEnd, t.end);
    }
    const duration =
      phaseStart !== undefined && phaseEnd !== undefined && phaseEnd >= phaseStart
        ? (phaseEnd - phaseStart) / 1000
        : null;

    const phaseSteps: PhaseStep[] = [];
    for (const s of steps) {
      let belongs = false;
      if (s.stage.startsWith('langgraph_')) {
        const node = nodeOf(s.stage);
        belongs = phase.nodes.some((pattern) => nodeMatches(node, pattern));
      }
      if (!belongs) {
        belongs = phase.altStages.some((alt) => s.stage === alt);
      }
      if (!belongs && phase.id === 'execute') {
        belongs = s.stage.startsWith('agent_') || s.stage.startsWith('executor_step_');
      }

      if (belongs) {
        const agentName = s.result?.agent ?? s.result?.agent_name ?? undefined;
        phaseSteps.push({
          stage: s.stage,
          message: getStepMessage(s),
          timestamp: s.timestamp,
          isDone:
            s.stage.endsWith('_done') ||
            s.stage === 'understanding' ||
            s.stage === 'classified' ||
            s.stage === 'complete',
          agentName: typeof agentName === 'string' ? agentName : undefined,
        });
      }
    }

    return {
      id: phase.id,
      label: phase.label,
      Icon: phase.Icon,
      status,
      steps: phaseSteps,
      duration,
    };
  });

  // 后续阶段进入 active/done 时，把更早的 active 阶段标记 done
  for (let i = 0; i < result.length - 1; i++) {
    if (result[i].status === 'active' && result.slice(i + 1).some((p) => p.status !== 'pending')) {
      result[i] = { ...result[i], status: 'done' };
    }
  }

  // 全局完成态短路：闲聊场景 chat_respond_done / save_memory_done / done 任一触发都强制收尾
  const hasGlobalDone = steps.some((s) => {
    if (s.eventType === 'done') return true;
    if (s.stage === 'done') return true;
    if (s.stage === 'langgraph_chat_respond_done') return true;
    if (s.stage === 'langgraph_save_memory_done') return true;
    if (s.stage === 'langgraph_render_done') return true;
    if (s.stage === 'rendering' && s.result?.status === 'done') return true;
    return false;
  });
  if (hasGlobalDone) {
    for (let i = 0; i < result.length; i++) {
      if (result[i].status === 'active') {
        result[i] = { ...result[i], status: 'done' };
      }
    }
  }

  return result;
}

/* ===== Agent Extraction ===== */

function extractAgents(steps: ThinkingStep[]): AgentEntry[] {
  const map = new Map<string, AgentEntry & { _start?: number; _end?: number }>();

  for (const s of steps) {
    let agentName: string | null = null;
    let status: AgentEntry['status'] = 'running';
    const ts = Date.parse(s.timestamp);
    let isStart = false;
    let isEnd = false;

    if (s.stage === 'agent_start' || s.stage === 'agent_done' || s.stage === 'agent_error') {
      agentName = s.result?.agent ?? s.result?.agent_name ?? null;
      if (!agentName && typeof s.message === 'string' && s.message.includes('agent')) {
        agentName = s.message;
      }
      status = s.stage === 'agent_done' ? 'done' : s.stage === 'agent_error' ? 'error' : 'running';
      isStart = s.stage === 'agent_start';
      isEnd = s.stage === 'agent_done' || s.stage === 'agent_error';
    }

    if (
      s.stage === 'executor_step_start' ||
      s.stage === 'executor_step_done' ||
      s.stage === 'executor_step_error'
    ) {
      agentName = s.result?.agent ?? s.result?.agent_name ?? s.result?.step ?? null;
      status = s.stage.endsWith('_done')
        ? 'done'
        : s.stage.endsWith('_error')
          ? 'error'
          : 'running';
      isStart = s.stage.endsWith('_start');
      isEnd = s.stage.endsWith('_done') || s.stage.endsWith('_error');
    }

    if (agentName && typeof agentName === 'string') {
      const normalized = normalizeAgentName(agentName);
      const existing = map.get(normalized);
      const next: AgentEntry & { _start?: number; _end?: number } = existing
        ? { ...existing }
        : { name: normalized, displayName: getAgentDisplayName(agentName), status: 'running' };

      if (!existing || status === 'done' || (status === 'error' && existing.status === 'running')) {
        next.status = status;
        next.displayName = getAgentDisplayName(agentName);
      }

      // 置信度 (后端可能用 confidence / score)
      const conf =
        s.result?.confidence ??
        s.result?.score ??
        s.result?.confidence_score ??
        undefined;
      if (typeof conf === 'number' && Number.isFinite(conf)) {
        next.confidence = conf <= 1 ? Math.round(conf * 100) : Math.round(conf);
      }

      if (isStart && Number.isFinite(ts)) next._start = ts;
      if (isEnd && Number.isFinite(ts)) next._end = ts;
      if (next._start !== undefined && next._end !== undefined && next._end >= next._start) {
        next.duration = (next._end - next._start) / 1000;
      }

      map.set(normalized, next);
    }
  }

  return [...map.values()].map((entry) => {
    const rest = { ...entry };
    delete rest._start;
    delete rest._end;
    return rest;
  });
}

/* ===== Sub Components ===== */

interface ProgressRingProps {
  percent: number;
  size?: number;
  stroke?: number;
}

const ProgressRing: React.FC<ProgressRingProps> = ({ percent, size = 38, stroke = 3 }) => {
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - Math.max(0, Math.min(100, percent)) / 100);
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} style={{ transform: 'rotate(-90deg)' }}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke="currentColor"
          className="text-fin-border"
          strokeWidth={stroke}
          fill="none"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke="currentColor"
          className="text-fin-primary transition-[stroke-dashoffset] duration-500 ease-out"
          strokeWidth={stroke}
          fill="none"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
        />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center text-[10px] font-semibold text-fin-primary tabular-nums">
        {Math.round(percent)}
      </div>
    </div>
  );
};

interface AgentCardProps {
  agent: AgentEntry;
}

const AgentCard: React.FC<AgentCardProps> = ({ agent }) => {
  const isDone = agent.status === 'done';
  const isError = agent.status === 'error';
  const conf = agent.confidence;

  return (
    <div
      className={`
        flex flex-col gap-1 px-2 py-1.5 rounded-lg border text-2xs transition-colors
        ${isDone
          ? 'border-emerald-500/25 bg-emerald-500/5'
          : isError
            ? 'border-red-500/25 bg-red-500/5'
            : 'border-fin-primary/30 bg-fin-primary/5'}
      `}
    >
      <div className="flex items-center gap-1.5">
        {isDone && <CheckCircle2 size={10} className="text-emerald-400 shrink-0" />}
        {isError && <AlertTriangle size={10} className="text-red-400 shrink-0" />}
        {agent.status === 'running' && <Loader2 size={10} className="animate-spin text-fin-primary shrink-0" />}
        <span className={`flex-1 truncate font-medium ${isDone ? 'text-emerald-300' : isError ? 'text-red-300' : 'text-fin-primary'}`}>
          {agent.displayName}
        </span>
        {typeof conf === 'number' && (
          <span className="text-fin-muted tabular-nums text-[9px]">{conf}%</span>
        )}
      </div>
      {/* 进度条 */}
      <div className="h-[2px] rounded-full overflow-hidden bg-fin-border/60">
        <div
          className={`h-full rounded-full transition-[width] duration-500
            ${isDone ? 'bg-gradient-to-r from-fin-primary to-emerald-400' :
              isError ? 'bg-red-400' :
              'bg-gradient-to-r from-fin-primary via-cyan-400 to-fin-primary animate-pulse'}`}
          style={{ width: `${typeof conf === 'number' ? conf : isDone ? 100 : 60}%` }}
        />
      </div>
      {typeof agent.duration === 'number' && (
        <div className="flex items-center justify-between text-[9px] text-fin-muted tabular-nums">
          <span className="opacity-70">已完成</span>
          <span>{agent.duration.toFixed(1)}s</span>
        </div>
      )}
    </div>
  );
};

/* ===== Component ===== */

interface ThinkingUserViewProps {
  thinking: ThinkingStep[];
}

/**
 * ThinkingUserView — Cursor Composer 风格的分析过程视图。
 *
 * 设计基线：
 *   - 时间轴竖线：fin-primary → cyan-400 渐变
 *   - 阶段节点：done/active/pending 三态视觉
 *   - Agent 卡片：迷你进度条 + 置信度
 *   - 主题色严格使用 fin-primary（蓝色），辅以 cyan、emerald
 */
export const ThinkingUserView: React.FC<ThinkingUserViewProps> = ({ thinking }) => {
  const phases = useMemo(() => computePhases(thinking), [thinking]);
  const agents = useMemo(() => extractAgents(thinking), [thinking]);
  const [expandedPhases, setExpandedPhases] = useState<Set<string>>(new Set());

  const statusText = useMemo(() => {
    for (let i = thinking.length - 1; i >= 0; i--) {
      const step = thinking[i];
      if (step.result?.userMessage && typeof step.result.userMessage === 'string') {
        return step.result.userMessage;
      }
      if ((step.eventType === 'trace' || step.result?.type === 'trace') && step.message) {
        return step.message;
      }
      const msg = resolveUserMessage(thinking[i].stage);
      if (msg) return msg;
    }
    return null;
  }, [thinking]);

  const cancelledStep = useMemo(() => {
    for (let i = thinking.length - 1; i >= 0; i--) {
      const step = thinking[i];
      const resultStatus = typeof step.result?.status === 'string' ? step.result.status : '';
      if (step.stage === 'cancelled' || resultStatus === 'cancelled') {
        return step;
      }
    }
    return null;
  }, [thinking]);

  const allDone = phases.every((p) => p.status === 'done');
  const anyActive = phases.some((p) => p.status === 'active');

  const elapsed = useMemo(() => {
    if (thinking.length < 2) return null;
    const first = new Date(thinking[0].timestamp).getTime();
    const last = new Date(thinking[thinking.length - 1].timestamp).getTime();
    const diff = last - first;
    return diff > 0 ? (diff / 1000).toFixed(1) : null;
  }, [thinking]);

  // 进度百分比 = done / total
  const doneCount = phases.filter((p) => p.status === 'done').length;
  const visiblePhases = phases.filter((p) => p.status !== 'pending' || p.steps.length > 0);
  const progressPercent = phases.length > 0 ? (doneCount / phases.length) * 100 : 0;

  const togglePhase = (phaseId: string) => {
    const next = new Set(expandedPhases);
    if (next.has(phaseId)) next.delete(phaseId);
    else next.add(phaseId);
    setExpandedPhases(next);
  };

  // 闲聊兜底：连一个可见阶段都没有，但已 done → 直接显示 minimal banner
  if (visiblePhases.length === 0 && !cancelledStep) {
    if (allDone || thinking.length === 0) {
      return null; // 由父组件 ThinkingProcess 控制是否展示
    }
  }

  return (
    <div className="mt-3 space-y-3 animate-fade-in">
      {/* === Header === */}
      <div className="flex items-center gap-3 px-3 py-2 rounded-xl border border-fin-border/60 bg-fin-panel/40 backdrop-blur-sm">
        <ProgressRing percent={progressPercent} />
        <div className="flex-1 min-w-0">
          <div className="text-xs font-semibold text-fin-text leading-tight flex items-center gap-1.5">
            <Zap size={11} className="text-fin-primary" />
            分析过程
          </div>
          <div className="text-[10px] text-fin-muted mt-0.5 tabular-nums">
            {doneCount}/{phases.length} 阶段 · {thinking.length} 个事件
            {!allDone && anyActive && <span className="ml-1 text-fin-primary/80">· 进行中</span>}
          </div>
        </div>
        <div className="flex items-center gap-1 text-[10px] shrink-0">
          {elapsed && (
            <span className="px-1.5 py-0.5 rounded-full border border-fin-primary/25 bg-fin-primary/10 text-fin-primary tabular-nums">
              ⏱ {elapsed}s
            </span>
          )}
        </div>
      </div>

      {/* === Timeline === */}
      <div className="relative pl-5 pr-1">
        {/* 主轴竖线 —— FinSight 主题色蓝色渐变 */}
        <div
          aria-hidden
          className="absolute left-[7px] top-2 bottom-2 w-[2px] rounded-full bg-gradient-to-b from-fin-primary via-cyan-400/70 to-fin-primary/20 opacity-60"
        />

        {visiblePhases.map((phase) => {
          const isExpanded = expandedPhases.has(phase.id);
          const hasSteps = phase.steps.length > 0;
          const isClickable = hasSteps || phase.id === 'execute';
          const Icon = phase.Icon;

          return (
            <div key={phase.id} className="relative pb-2 last:pb-0">
              {/* 节点圆点 */}
              <div
                className={`
                  absolute -left-[18px] top-[5px] w-[16px] h-[16px] rounded-full
                  flex items-center justify-center text-[8px] font-bold shrink-0
                  transition-all duration-300
                  ${phase.status === 'done'
                    ? 'bg-emerald-500/15 border-2 border-emerald-400 text-emerald-400'
                    : phase.status === 'active'
                      ? 'bg-fin-primary/15 border-2 border-fin-primary text-fin-primary animate-pulse'
                      : 'bg-fin-bg border-2 border-fin-border'}
                `}
                style={
                  phase.status === 'active'
                    ? { boxShadow: '0 0 0 3px rgb(var(--fin-primary) / 0.15)' }
                    : undefined
                }
              >
                {phase.status === 'done' && '✓'}
                {phase.status === 'active' && (
                  <span className="w-1.5 h-1.5 rounded-full bg-fin-primary" />
                )}
              </div>

              {/* 行 */}
              <button
                type="button"
                onClick={() => isClickable && togglePhase(phase.id)}
                disabled={!isClickable}
                className={`
                  w-full flex items-center gap-2 px-2 py-1 rounded-md text-xs
                  transition-all duration-200
                  ${isClickable ? 'cursor-pointer hover:bg-fin-hover/40' : 'cursor-default'}
                  ${phase.status === 'done'
                    ? 'text-fin-text'
                    : phase.status === 'active'
                      ? 'text-fin-primary'
                      : 'text-fin-muted/60'}
                `}
              >
                <Icon
                  size={12}
                  className={`shrink-0 ${
                    phase.status === 'done'
                      ? 'text-emerald-400'
                      : phase.status === 'active'
                        ? 'text-fin-primary'
                        : 'text-fin-muted/60'
                  }`}
                />
                <span className="flex-1 text-left font-medium">{phase.label}</span>
                {hasSteps && (
                  <span className="text-[9px] text-fin-muted/70 tabular-nums">
                    {phase.steps.length} 步
                  </span>
                )}
                {phase.duration !== null && (
                  <span
                    className={`text-[10px] tabular-nums shrink-0 ${
                      phase.duration > 3 ? 'text-amber-400' : 'text-fin-muted'
                    }`}
                  >
                    {phase.duration.toFixed(1)}s
                  </span>
                )}
                {isClickable && (
                  isExpanded ? (
                    <ChevronDown size={10} className="text-fin-muted/60 shrink-0" />
                  ) : (
                    <ChevronRight size={10} className="text-fin-muted/60 shrink-0" />
                  )
                )}
              </button>

              {/* 展开 —— 子步骤 + agent 网格 */}
              {isExpanded && (
                <div className="ml-4 mt-1 pl-3 border-l border-dashed border-fin-border/50 space-y-0.5 animate-fade-in">
                  {phase.steps.map((step, idx) => (
                    <div
                      key={`${step.stage}-${idx}`}
                      className="flex items-start gap-2 py-0.5 text-[11px] leading-relaxed"
                    >
                      {step.isDone ? (
                        <CheckCircle2 size={9} className="text-emerald-400/70 shrink-0 mt-[3px]" />
                      ) : (
                        <Clock size={9} className="text-fin-primary/70 shrink-0 mt-[3px]" />
                      )}
                      <span className={`flex-1 ${step.isDone ? 'text-fin-muted' : 'text-fin-text/85'}`}>
                        {step.message}
                        {step.agentName && (
                          <span className="ml-1 inline-flex items-center px-1.5 py-px rounded-sm border border-cyan-400/25 bg-cyan-400/8 text-cyan-300/90 text-[9px] font-medium align-middle">
                            {getAgentDisplayName(step.agentName)}
                          </span>
                        )}
                      </span>
                      <span className="text-fin-muted/40 tabular-nums shrink-0 text-[9px] mt-[3px]">
                        {formatTime(step.timestamp)}
                      </span>
                    </div>
                  ))}

                  {/* Agent 卡片网格 —— 仅在 execute 阶段显示 */}
                  {phase.id === 'execute' && agents.length > 0 && (
                    <div className="mt-2 grid grid-cols-2 gap-1.5">
                      {agents.map((agent) => (
                        <AgentCard key={agent.name} agent={agent} />
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* === Agent 摘要（execute 未展开时也展示） === */}
      {agents.length > 0 && !expandedPhases.has('execute') && (
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5 text-[10px] text-fin-muted px-1">
            <Sparkles size={10} className="text-fin-primary/70" />
            <span>分析师团队</span>
            <span className="tabular-nums">
              ({agents.filter((a) => a.status === 'done').length}/{agents.length})
            </span>
          </div>
          <div className="grid grid-cols-2 gap-1.5">
            {agents.map((agent) => (
              <AgentCard key={agent.name} agent={agent} />
            ))}
          </div>
        </div>
      )}

      {/* === 进行中状态横幅 === */}
      {statusText && anyActive && !cancelledStep && (
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-[11px] bg-fin-primary/8 text-fin-primary border border-fin-primary/20 animate-fade-in">
          <Loader2 size={11} className="animate-spin shrink-0" />
          <span className="truncate flex-1">{statusText}</span>
        </div>
      )}

      {/* === 取消横幅 === */}
      {cancelledStep && (
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-[11px] bg-amber-500/10 text-amber-300 border border-amber-500/25">
          <AlertTriangle size={11} className="shrink-0" />
          <span className="truncate">{getStepMessage(cancelledStep)}</span>
        </div>
      )}

      {/* === 完成横幅 === */}
      {allDone && !cancelledStep && (
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-[11px] bg-emerald-500/10 text-emerald-300 border border-emerald-500/25 animate-fade-in">
          <CheckCircle2 size={12} className="shrink-0" />
          <span className="flex-1">
            分析完成
            {elapsed ? ` · 耗时 ${elapsed}s` : ''}
            {' · '}
            共 {thinking.length} 步
            {agents.length > 0 ? ` · ${agents.length} 位分析师参与` : ''}
          </span>
        </div>
      )}
    </div>
  );
};
