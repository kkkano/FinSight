import React, { useMemo, useState } from 'react';
import { CheckCircle2, ChevronDown, ChevronRight, Loader2, AlertTriangle, Clock } from 'lucide-react';
import type { ThinkingStep } from '../../types';
import { resolveUserMessage, getAgentDisplayName, normalizeAgentName } from '../../utils/userMessageMapper';

/* ===== Phase Configuration ===== */
const PHASES = [
  {
    id: 'understand',
    label: '理解意图',
    emoji: '🔍',
    // langgraph node prefixes
    nodes: [
      'build_initial_state', 'reset_turn', 'trim', 'summarize',
      'normalize', 'decide_output', 'chat_respond',
      'resolve_subject', 'clarify', 'parse_operation',
    ],
    // supervisor / streaming stage names
    altStages: ['classifying', 'classified', 'intent_classification'],
    doneMarker: 'parse_operation',
    altDoneStages: ['classified'],
  },
  {
    id: 'plan',
    label: '规划策略',
    emoji: '📋',
    nodes: ['policy_gate', 'planner', 'confirmation_gate'],
    altStages: ['agent_gate', 'agent_selected'],
    doneMarker: 'planner',
    altDoneStages: ['agent_selected'],
  },
  {
    id: 'execute',
    label: '执行分析',
    emoji: '🔬',
    nodes: ['execute_plan'],
    altStages: ['processing', 'data_collection', 'agent_start', 'agent_done', 'executor_step_start', 'executor_step_done'],
    doneMarker: 'execute_plan',
    altDoneStages: ['complete'],
  },
  {
    id: 'synthesize',
    label: '整合报告',
    emoji: '📊',
    nodes: ['synthesize', 'render', 'save_memory'],
    altStages: ['rendering', 'complete'],
    doneMarker: 'render',
    altDoneStages: ['complete'],
  },
] as const;

type PhaseStatus = 'pending' | 'active' | 'done';

interface ComputedPhase {
  id: string;
  label: string;
  emoji: string;
  status: PhaseStatus;
  /** Steps that belong to this phase */
  steps: PhaseStep[];
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
}

/* ===== Helpers ===== */

/** "langgraph_planner_start" → "planner" */
function nodeOf(stage: string): string {
  return stage.replace(/^langgraph_/, '').replace(/_(start|done)$/, '');
}

/** Check if node matches pattern (prefix-based) */
function nodeMatches(node: string, pattern: string): boolean {
  return node === pattern || node.startsWith(pattern);
}

/** Format timestamp to HH:MM:SS */
function formatTime(ts: string): string {
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch {
    return '';
  }
}

/** Get step message from stage */
function getStepMessage(step: ThinkingStep): string {
  // Backend userMessage first
  if (step.result?.userMessage && typeof step.result.userMessage === 'string') {
    return step.result.userMessage;
  }
  // Frontend mapping
  const mapped = resolveUserMessage(step.stage);
  if (mapped) return mapped;
  // Fallback: human-readable stage name
  if (step.message && typeof step.message === 'string') return step.message;
  return step.stage.replace(/^langgraph_/, '').replace(/_/g, ' ');
}

/* ===== Phase Computation ===== */

function computePhases(steps: ThinkingStep[]): ComputedPhase[] {
  const startedNodes = new Set<string>();
  const doneNodes = new Set<string>();
  const allStages = new Set<string>();

  for (const s of steps) {
    allStages.add(s.stage);
    if (s.stage.startsWith('langgraph_')) {
      const node = nodeOf(s.stage);
      if (s.stage.endsWith('_start')) startedNodes.add(node);
      if (s.stage.endsWith('_done')) doneNodes.add(node);
    }
  }

  const result: ComputedPhase[] = PHASES.map((phase) => {
    // Check langgraph path
    const hasLgStarted = phase.nodes.some((pattern) =>
      [...startedNodes].some((n) => nodeMatches(n, pattern)),
    );
    const lgMarkerDone = [...doneNodes].some((n) =>
      nodeMatches(n, phase.doneMarker),
    );

    // Check supervisor/streaming path (altStages)
    const hasAltStarted = phase.altStages.some((s) => allStages.has(s));
    const altDone = phase.altDoneStages.some((s) => allStages.has(s));

    const hasStarted = hasLgStarted || hasAltStarted;
    const markerDone = lgMarkerDone || altDone;

    let status: PhaseStatus = 'pending';
    if (markerDone) {
      status = 'done';
    } else if (hasStarted) {
      status = 'active';
    }

    // Collect steps belonging to this phase
    const phaseSteps: PhaseStep[] = [];
    for (const s of steps) {
      let belongs = false;

      // langgraph path
      if (s.stage.startsWith('langgraph_')) {
        const node = nodeOf(s.stage);
        belongs = phase.nodes.some((pattern) => nodeMatches(node, pattern));
      }

      // alt stages
      if (!belongs) {
        belongs = phase.altStages.some((alt) => s.stage === alt);
      }

      // Agent events belong to execute phase
      if (!belongs && phase.id === 'execute') {
        belongs = s.stage.startsWith('agent_') || s.stage.startsWith('executor_step_');
      }

      if (belongs) {
        const agentName = s.result?.agent ?? s.result?.agent_name ?? undefined;
        phaseSteps.push({
          stage: s.stage,
          message: getStepMessage(s),
          timestamp: s.timestamp,
          isDone: s.stage.endsWith('_done') || s.stage === 'classified' || s.stage === 'complete',
          agentName: typeof agentName === 'string' ? agentName : undefined,
        });
      }
    }

    return { id: phase.id, label: phase.label, emoji: phase.emoji, status, steps: phaseSteps };
  });

  // If a later phase is active/done, earlier active phases should be marked done
  for (let i = 0; i < result.length - 1; i++) {
    if (
      result[i].status === 'active' &&
      result.slice(i + 1).some((p) => p.status !== 'pending')
    ) {
      result[i] = { ...result[i], status: 'done' };
    }
  }

  return result;
}

/* ===== Agent Extraction ===== */

function extractAgents(steps: ThinkingStep[]): AgentEntry[] {
  const map = new Map<string, AgentEntry>();

  for (const s of steps) {
    let agentName: string | null = null;
    let status: AgentEntry['status'] = 'running';

    if (
      s.stage === 'agent_start' ||
      s.stage === 'agent_done' ||
      s.stage === 'agent_error'
    ) {
      agentName = s.result?.agent ?? s.result?.agent_name ?? null;
      if (!agentName && typeof s.message === 'string' && s.message.includes('agent')) {
        agentName = s.message;
      }
      status =
        s.stage === 'agent_done'
          ? 'done'
          : s.stage === 'agent_error'
            ? 'error'
            : 'running';
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
    }

    if (agentName && typeof agentName === 'string') {
      const normalized = normalizeAgentName(agentName);
      const existing = map.get(normalized);
      if (
        !existing ||
        status === 'done' ||
        (status === 'error' && existing.status === 'running')
      ) {
        map.set(normalized, {
          name: normalized,
          displayName: getAgentDisplayName(agentName),
          status,
        });
      }
    }
  }

  return [...map.values()];
}

/* ===== Component ===== */

interface ThinkingUserViewProps {
  thinking: ThinkingStep[];
}

/**
 * ThinkingUserView — user-mode analysis progress view.
 *
 * Shows 4 expandable phases + agent cards + completion banner.
 * Supports both LangGraph and supervisor/streaming stage paths.
 */
export const ThinkingUserView: React.FC<ThinkingUserViewProps> = ({ thinking }) => {
  const phases = useMemo(() => computePhases(thinking), [thinking]);
  const agents = useMemo(() => extractAgents(thinking), [thinking]);
  const [expandedPhases, setExpandedPhases] = useState<Set<string>>(new Set());

  // Last meaningful user-friendly message
  const statusText = useMemo(() => {
    for (let i = thinking.length - 1; i >= 0; i--) {
      const msg = resolveUserMessage(thinking[i].stage);
      if (msg) return msg;
    }
    return null;
  }, [thinking]);

  const allDone = phases.every((p) => p.status === 'done');
  const anyActive = phases.some((p) => p.status === 'active');

  // Elapsed time
  const elapsed = useMemo(() => {
    if (thinking.length < 2) return null;
    const first = new Date(thinking[0].timestamp).getTime();
    const last = new Date(thinking[thinking.length - 1].timestamp).getTime();
    const diff = last - first;
    return diff > 0 ? (diff / 1000).toFixed(1) : null;
  }, [thinking]);

  const togglePhase = (phaseId: string) => {
    const next = new Set(expandedPhases);
    if (next.has(phaseId)) {
      next.delete(phaseId);
    } else {
      next.add(phaseId);
    }
    setExpandedPhases(next);
  };

  return (
    <div className="mt-2 space-y-1.5">
      {/* Phase Milestones */}
      <div className="space-y-0.5">
        {phases.map((phase) => {
          const isExpanded = expandedPhases.has(phase.id);
          const hasSteps = phase.steps.length > 0;
          const isClickable = hasSteps || phase.status !== 'pending';

          return (
            <div key={phase.id}>
              {/* Phase header row */}
              <button
                type="button"
                onClick={() => isClickable && togglePhase(phase.id)}
                disabled={!isClickable}
                className={`
                  w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-xs
                  transition-all duration-300
                  ${isClickable ? 'cursor-pointer hover:bg-fin-hover/30' : 'cursor-default'}
                  ${phase.status === 'done'
                    ? 'text-emerald-300'
                    : phase.status === 'active'
                      ? 'text-blue-200'
                      : 'text-fin-muted/50'
                  }
                `}
              >
                {/* Status icon */}
                {phase.status === 'done' && (
                  <CheckCircle2 size={13} className="text-emerald-400 shrink-0" />
                )}
                {phase.status === 'active' && (
                  <Loader2 size={13} className="animate-spin text-blue-400 shrink-0" />
                )}
                {phase.status === 'pending' && (
                  <div className="w-[13px] h-[13px] rounded-full border border-fin-border/50 shrink-0" />
                )}

                {/* Label */}
                <span className="flex-1 text-left">
                  {phase.emoji} {phase.label}
                  {hasSteps && (
                    <span className="ml-1 text-fin-muted/60 text-2xs">
                      ({phase.steps.length})
                    </span>
                  )}
                </span>

                {/* Expand chevron */}
                {isClickable && (
                  isExpanded
                    ? <ChevronDown size={12} className="text-fin-muted/60 shrink-0" />
                    : <ChevronRight size={12} className="text-fin-muted/60 shrink-0" />
                )}
              </button>

              {/* Expanded step details */}
              {isExpanded && hasSteps && (
                <div className="ml-7 mb-1 space-y-0.5 border-l-2 border-fin-border/30 pl-3">
                  {phase.steps.map((step, idx) => (
                    <div
                      key={`${step.stage}-${idx}`}
                      className={`
                        flex items-start gap-2 py-0.5 text-2xs
                        ${step.isDone ? 'text-fin-muted/70' : 'text-fin-text/80'}
                      `}
                    >
                      {step.isDone ? (
                        <CheckCircle2 size={10} className="text-emerald-500/60 shrink-0 mt-0.5" />
                      ) : (
                        <Clock size={10} className="text-blue-400/60 shrink-0 mt-0.5" />
                      )}
                      <span className="flex-1 leading-relaxed">
                        {step.message}
                        {step.agentName && (
                          <span className="ml-1 text-fin-primary/70">
                            [{getAgentDisplayName(step.agentName)}]
                          </span>
                        )}
                      </span>
                      <span className="text-fin-muted/40 tabular-nums shrink-0">
                        {formatTime(step.timestamp)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Active Status Message */}
      {statusText && anyActive && (
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs bg-blue-500/5 text-blue-200/80 border border-blue-500/10">
          <Loader2 size={12} className="animate-spin text-blue-400 shrink-0" />
          <span className="truncate">{statusText}</span>
        </div>
      )}

      {/* Agent Summary Cards */}
      {agents.length > 0 && (
        <div className="space-y-1">
          <div className="text-2xs text-fin-muted px-1">
            分析师团队 (
            {agents.filter((a) => a.status === 'done').length}/{agents.length}{' '}
            完成)
          </div>
          <div className="grid grid-cols-2 gap-1">
            {agents.map((agent) => (
              <div
                key={agent.name}
                className={`
                  flex items-center gap-1.5 px-2 py-1 rounded-md text-2xs
                  border transition-colors duration-200
                  ${agent.status === 'done'
                    ? 'border-emerald-500/20 bg-emerald-500/5 text-emerald-300'
                    : agent.status === 'error'
                      ? 'border-red-500/20 bg-red-500/5 text-red-300'
                      : 'border-blue-500/20 bg-blue-500/5 text-blue-200'
                  }
                `}
              >
                {agent.status === 'done' && (
                  <CheckCircle2 size={11} className="text-emerald-400 shrink-0" />
                )}
                {agent.status === 'running' && (
                  <Loader2 size={11} className="animate-spin text-blue-400 shrink-0" />
                )}
                {agent.status === 'error' && (
                  <AlertTriangle size={11} className="text-red-400 shrink-0" />
                )}
                <span className="truncate">{agent.displayName}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Completion Banner */}
      {allDone && (
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs bg-emerald-500/10 text-emerald-300 border border-emerald-500/20">
          <CheckCircle2 size={13} className="text-emerald-400 shrink-0" />
          <span>
            分析完成
            {elapsed ? `（耗时 ${elapsed}s）` : ''}
            ，共 {thinking.length} 步
          </span>
        </div>
      )}
    </div>
  );
};
