/**
 * ExecutionStore - global Zustand store for agent execution state.
 *
 * Contracts:
 * - runId lifecycle: created in startExecution, immutable until completion
 * - Progress is monotonically increasing
 * - Terminal states move runs from activeRuns to recentRuns
 */
import { create } from 'zustand';

import { apiClient } from '../api/client';
import type { ExecuteRequest, SSECallbacks } from '../api/client';
import { getAgentPreferences } from '../components/settings/AgentControlPanel';
import type {
  AgentRunInfo,
  DecisionNote,
  ExecutionRun,
  PipelineStage,
  PipelineStageState,
  PlanStepSummary,
  StartExecutionParams,
  TimelineEvent,
} from '../types/execution';
import type { ReportIR } from '../types/index';
import { useStore } from './useStore';

const MAX_RECENT_RUNS = 20;
const MAX_TIMELINE_EVENTS = 300;

const PIPELINE_STAGE_ORDER: PipelineStage[] = [
  'planning',
  'executing',
  'synthesizing',
  'rendering',
  'done',
];

const PIPELINE_STAGE_BASE_PROGRESS: Record<PipelineStage, number> = {
  planning: 8,
  executing: 38,
  synthesizing: 82,
  rendering: 93,
  done: 100,
};

interface ExecutionState {
  activeRuns: ExecutionRun[];
  recentRuns: ExecutionRun[];
  startExecution: (params: StartExecutionParams) => string;
  beginExternalExecution: (params: {
    runId: string;
    query: string;
    tickers?: string[];
    source: string;
    outputMode?: string;
    analysisDepth?: ExecutionRun['analysisDepth'];
  }) => void;
  ingestExternalThinking: (runId: string, step: any) => void;
  ingestExternalToken: (runId: string, token?: string) => void;
  completeExternalExecution: (params: {
    runId: string;
    status: 'done' | 'error' | 'cancelled';
    report?: ReportIR | null;
    error?: string | null;
    meta?: Record<string, unknown>;
  }) => void;
  interruptExternalExecution: (runId: string, data: {
    thread_id: string;
    prompt?: string;
    options?: string[];
    plan_summary?: string;
    required_agents?: string[];
  }) => void;
  cancelExecution: (runId: string) => void;
  getActiveRunForTicker: (ticker: string) => ExecutionRun | undefined;
  markBridged: (runId: string) => void;
}

function createInitialPipelineStages(): Record<PipelineStage, PipelineStageState> {
  return {
    planning: { stage: 'planning', status: 'pending' },
    executing: { stage: 'executing', status: 'pending' },
    synthesizing: { stage: 'synthesizing', status: 'pending' },
    rendering: { stage: 'rendering', status: 'pending' },
    done: { stage: 'done', status: 'pending' },
  };
}

function calculateAgentProgress(
  agentStatuses: Record<string, AgentRunInfo>,
  currentProgress: number,
): number {
  const agents = Object.values(agentStatuses);
  const total = Math.max(agents.length, 1);
  const completed = agents.filter(
    (agent) => agent.status === 'done' || agent.status === 'error',
  ).length;
  const calculated = 10 + Math.round((completed / total) * 70);
  return Math.max(currentProgress, calculated);
}

function pushTimeline(
  run: ExecutionRun,
  event: TimelineEvent,
): TimelineEvent[] {
  return [...run.timeline, event].slice(-MAX_TIMELINE_EVENTS);
}

function buildTimelineEvent(
  runId: string,
  step: any,
  runIdFromEvent?: string,
): TimelineEvent {
  const result = (step?.result && typeof step.result === 'object')
    ? step.result
    : {};
  const raw = result as Record<string, unknown>;
  const eventType = String(step?.eventType || raw.type || step?.stage || 'thinking');
  const stage = String(step?.stage || raw.stage || eventType || 'thinking');

  return {
    id: `${runId}:${Date.now()}:${Math.random().toString(36).slice(2, 8)}`,
    timestamp: String(step?.timestamp || new Date().toISOString()),
    eventType,
    stage,
    message: typeof step?.message === 'string' ? step.message : undefined,
    runId: runIdFromEvent || runId,
    sessionId: typeof step?.sessionId === 'string' ? step.sessionId : undefined,
    stepId: typeof raw.step_id === 'string' ? raw.step_id : undefined,
    kind: typeof raw.kind === 'string' ? raw.kind : undefined,
    name: typeof raw.name === 'string' ? raw.name : undefined,
    agent: typeof raw.agent === 'string' ? raw.agent : undefined,
    tool: typeof raw.tool === 'string'
      ? raw.tool
      : (eventType.startsWith('tool_') && typeof raw.name === 'string' ? raw.name : undefined),
    durationMs: typeof raw.duration_ms === 'number' ? raw.duration_ms : undefined,
    cached: raw.cached === true,
    skipped: raw.skipped === true,
    status: typeof raw.status === 'string' ? raw.status : undefined,
    parallelGroup: typeof raw.parallel_group === 'string' ? raw.parallel_group : null,
    raw,
  };
}

function normalizePipelineStage(value: unknown): PipelineStage | null {
  const raw = String(value || '').trim().toLowerCase();
  if (!raw) return null;
  if (raw === 'planning') return 'planning';
  if (raw === 'executing') return 'executing';
  if (raw === 'synthesizing') return 'synthesizing';
  if (raw === 'rendering') return 'rendering';
  if (raw === 'done') return 'done';
  return null;
}

function normalizePipelineStatus(value: unknown): PipelineStageState['status'] {
  const raw = String(value || '').trim().toLowerCase();
  if (!raw) return 'running';
  if (raw === 'start' || raw === 'running' || raw === 'resume') return 'running';
  if (raw === 'done' || raw === 'success' || raw === 'completed') return 'done';
  if (raw === 'error' || raw === 'failed') return 'error';
  return 'pending';
}

function asFiniteNumber(value: unknown): number | undefined {
  if (typeof value !== 'number' || !Number.isFinite(value)) return undefined;
  return value;
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => (typeof item === 'string' ? item.trim() : ''))
    .filter((item) => Boolean(item));
}

function asPlanSteps(value: unknown): PlanStepSummary[] {
  if (!Array.isArray(value)) return [];
  const steps: PlanStepSummary[] = [];
  for (const item of value) {
    if (!item || typeof item !== 'object') continue;
    const row = item as Record<string, unknown>;
    const id = typeof row.id === 'string' ? row.id.trim() : '';
    const kind = typeof row.kind === 'string' ? row.kind.trim() : '';
    const name = typeof row.name === 'string' ? row.name.trim() : '';
    if (!id || !kind || !name) continue;
    steps.push({
      id,
      kind,
      name,
      parallelGroup: typeof row.parallel_group === 'string'
        ? row.parallel_group
        : (typeof row.parallelGroup === 'string' ? row.parallelGroup : null),
      optional: row.optional === true,
    });
  }
  return steps;
}

function computeEstimatedEtaSeconds(run: ExecutionRun): number | null {
  if (run.status !== 'running') return null;

  const completedDurations = run.timeline
    .filter((event) => event.eventType === 'step_done' && typeof event.durationMs === 'number')
    .map((event) => Number(event.durationMs));

  if (completedDurations.length === 0) return null;

  const avgDurationMs = completedDurations.reduce((sum, item) => sum + item, 0) / completedDurations.length;
  const doneSteps = run.timeline.filter((event) => event.eventType === 'step_done').length;
  const totalSteps = run.planSteps?.length ?? 0;

  if (totalSteps > 0) {
    const remainingSteps = Math.max(0, totalSteps - doneSteps);
    if (remainingSteps <= 0) return null;
    return Math.max(1, Math.round((avgDurationMs * remainingSteps) / 1000));
  }

  const currentStage = run.pipelineCurrentStage;
  if (!currentStage) return null;
  const index = PIPELINE_STAGE_ORDER.indexOf(currentStage);
  if (index < 0) return null;
  const remainingStages = Math.max(0, PIPELINE_STAGE_ORDER.length - 1 - index);
  if (remainingStages <= 0) return null;
  return Math.max(1, Math.round((avgDurationMs * remainingStages * 1.5) / 1000));
}

function pushDecisionNote(existing: DecisionNote[] | undefined, note: DecisionNote): DecisionNote[] {
  const next = [...(existing ?? []), note];
  return next.slice(-24);
}

function mergePatchAndEstimateEta(run: ExecutionRun, patch: Partial<ExecutionRun>): Partial<ExecutionRun> {
  const nextRun: ExecutionRun = {
    ...run,
    ...patch,
    timeline: patch.timeline ?? run.timeline,
    pipelineStages: patch.pipelineStages ?? run.pipelineStages,
    decisionNotes: patch.decisionNotes ?? run.decisionNotes,
    agentStatuses: patch.agentStatuses ?? run.agentStatuses,
    planSteps: patch.planSteps ?? run.planSteps,
    selectedAgents: patch.selectedAgents ?? run.selectedAgents,
    skippedAgents: patch.skippedAgents ?? run.skippedAgents,
  };

  if (nextRun.status === 'running') {
    patch.etaSeconds = computeEstimatedEtaSeconds(nextRun);
  } else {
    patch.etaSeconds = null;
  }
  return patch;
}

function createExecutionRunState(params: {
  runId: string;
  query: string;
  tickers?: string[];
  source: string;
  outputMode?: string;
  analysisDepth?: ExecutionRun['analysisDepth'];
  abortController?: AbortController | null;
}): ExecutionRun {
  const now = new Date().toISOString();
  return {
    runId: params.runId,
    query: params.query,
    tickers: params.tickers ?? [],
    source: params.source,
    outputMode: params.outputMode ?? 'brief',
    analysisDepth: params.analysisDepth,
    status: 'running',
    agentStatuses: {},
    pipelineStages: createInitialPipelineStages(),
    pipelineCurrentStage: null,
    selectedAgents: [],
    skippedAgents: [],
    planSteps: [],
    hasParallelPlan: false,
    reasoningBrief: undefined,
    decisionNotes: [],
    etaSeconds: null,
    progress: 0,
    currentStep: '准备执行...',
    timeline: [],
    report: null,
    streamedContent: '',
    fallbackReasons: [],
    error: null,
    startedAt: now,
    completedAt: null,
    abortController: params.abortController ?? null,
    bridgedToChat: false,
    interruptData: null,
  };
}

export function pipelineReducer(run: ExecutionRun, step: any, timeline: TimelineEvent[]): Partial<ExecutionRun> {
  const result = (step?.result && typeof step.result === 'object')
    ? (step.result as Record<string, unknown>)
    : {};
  const eventType = String(step?.eventType || result.type || step?.stage || '').trim().toLowerCase();
  const stage = String(step?.stage || '').trim().toLowerCase();
  const message = String(step?.message || '').trim();
  const patch: Partial<ExecutionRun> = { timeline };

  if (eventType === 'plan_ready' || stage === 'plan_ready') {
    const planSteps = asPlanSteps(result.plan_steps);
    patch.planSteps = planSteps;
    patch.selectedAgents = asStringArray(result.selected_agents ?? result.agents);
    patch.skippedAgents = asStringArray(result.skipped_agents);
    patch.hasParallelPlan = result.has_parallel === true;
    patch.reasoningBrief = typeof result.reasoning_brief === 'string' ? result.reasoning_brief : undefined;
    patch.currentStep = message || '计划已生成';
    patch.progress = Math.max(run.progress, 8);
    return mergePatchAndEstimateEta(run, patch);
  }

  if (eventType === 'pipeline_stage') {
    const stageName = normalizePipelineStage(result.stage ?? step?.stage);
    if (stageName) {
      const nextStages = { ...(run.pipelineStages ?? createInitialPipelineStages()) };
      const status = normalizePipelineStatus(result.status);
      const existing = nextStages[stageName] ?? { stage: stageName, status: 'pending' };
      const timestamp = typeof step?.timestamp === 'string' ? step.timestamp : new Date().toISOString();
      nextStages[stageName] = {
        ...existing,
        status,
        message: message || (typeof result.message === 'string' ? result.message : existing.message),
        startedAt: status === 'running' ? (existing.startedAt ?? timestamp) : existing.startedAt,
        completedAt: status === 'done' || status === 'error' ? timestamp : existing.completedAt,
        durationMs: asFiniteNumber(result.duration_ms) ?? existing.durationMs,
        error: typeof result.error === 'string' ? result.error : existing.error,
      };
      patch.pipelineStages = nextStages;
      patch.pipelineCurrentStage = stageName;
      patch.currentStep = message || nextStages[stageName].message || run.currentStep;
      const stageProgress = PIPELINE_STAGE_BASE_PROGRESS[stageName];
      if (status === 'running') {
        patch.progress = Math.max(run.progress, Math.max(stageProgress - 3, 0));
      } else if (status === 'done') {
        patch.progress = Math.max(run.progress, stageProgress);
      } else if (status === 'error') {
        patch.progress = Math.max(run.progress, Math.max(stageProgress - 1, 0));
      }
      return mergePatchAndEstimateEta(run, patch);
    }
  }

  if (eventType === 'decision_note' || stage === 'decision_note') {
    const note: DecisionNote = {
      id: `${run.runId}:decision:${Date.now()}:${Math.random().toString(36).slice(2, 8)}`,
      scope: typeof result.scope === 'string' ? result.scope : undefined,
      title: typeof result.title === 'string' && result.title.trim() ? result.title : '决策说明',
      reason: typeof result.reason === 'string' ? result.reason : undefined,
      impact: typeof result.impact === 'string' ? result.impact : undefined,
      nextStep: typeof result.next_step === 'string'
        ? result.next_step
        : (typeof result.nextStep === 'string' ? result.nextStep : undefined),
      timestamp: typeof step?.timestamp === 'string' ? step.timestamp : new Date().toISOString(),
    };
    patch.decisionNotes = pushDecisionNote(run.decisionNotes, note);
    patch.currentStep = message || note.title;
    return mergePatchAndEstimateEta(run, patch);
  }

  if (eventType === 'supervisor_start' || stage === 'supervisor_start') {
    const agentNames: string[] = Array.isArray(result.agents) ? result.agents.map((name) => String(name)) : [];
    const newStatuses: Record<string, AgentRunInfo> = {};
    for (const name of agentNames) {
      const agentName = name.trim();
      if (!agentName) continue;
      newStatuses[agentName] = { name: agentName, status: 'pending' };
    }
    patch.agentStatuses = { ...run.agentStatuses, ...newStatuses };
    patch.progress = Math.max(run.progress, 5);
    patch.currentStep = message || '协调器已启动';
    return mergePatchAndEstimateEta(run, patch);
  }

  if (eventType === 'agent_start' || stage === 'agent_start') {
    const agentName = typeof result.agent === 'string' ? result.agent : undefined;
    if (agentName) {
      const statuses = { ...run.agentStatuses };
      if (!statuses[agentName]) {
        statuses[agentName] = { name: agentName, status: 'pending' };
      }
      statuses[agentName] = {
        ...statuses[agentName],
        status: 'running',
        startedAt: typeof step?.timestamp === 'string' ? step.timestamp : new Date().toISOString(),
      };
      patch.agentStatuses = statuses;
      patch.progress = calculateAgentProgress(statuses, run.progress);
      patch.currentStep = `${agentName} 执行中...`;
      return mergePatchAndEstimateEta(run, patch);
    }
  }

  if (eventType === 'agent_done' || stage === 'agent_done') {
    const agentName = typeof result.agent === 'string' ? result.agent : undefined;
    if (agentName) {
      const statuses = { ...run.agentStatuses };
      const existing = statuses[agentName] ?? { name: agentName, status: 'pending' as const };
      statuses[agentName] = {
        ...existing,
        status: 'done',
        completedAt: typeof step?.timestamp === 'string' ? step.timestamp : new Date().toISOString(),
        confidence: asFiniteNumber(result.confidence) ?? existing.confidence,
        evidenceCount: asFiniteNumber(result.evidence_count) ?? existing.evidenceCount,
        dataSources: asStringArray(result.data_sources).length > 0
          ? asStringArray(result.data_sources)
          : existing.dataSources,
        durationMs: asFiniteNumber(result.duration_ms) ?? existing.durationMs,
      };
      patch.agentStatuses = statuses;
      patch.progress = calculateAgentProgress(statuses, run.progress);
      patch.currentStep = `${agentName} 完成`;
      return mergePatchAndEstimateEta(run, patch);
    }
  }

  if (eventType === 'agent_error' || stage === 'agent_error') {
    const agentName = typeof result.agent === 'string' ? result.agent : undefined;
    if (agentName) {
      const statuses = { ...run.agentStatuses };
      const existing = statuses[agentName] ?? { name: agentName, status: 'pending' as const };
      const errorText = typeof result.error === 'string' ? result.error : 'Unknown error';
      statuses[agentName] = {
        ...existing,
        status: 'error',
        error: errorText,
        completedAt: typeof step?.timestamp === 'string' ? step.timestamp : new Date().toISOString(),
      };
      const fallbackReasons = [...run.fallbackReasons];
      if (errorText) fallbackReasons.push(`${agentName}: ${errorText}`);
      patch.agentStatuses = statuses;
      patch.fallbackReasons = fallbackReasons;
      patch.progress = calculateAgentProgress(statuses, run.progress);
      patch.currentStep = `${agentName} 异常`;
      return mergePatchAndEstimateEta(run, patch);
    }
  }

  if (message) {
    patch.currentStep = message;
  }

  if (eventType.includes('synth')) {
    patch.progress = Math.max(run.progress, 88);
  } else if (eventType.includes('render')) {
    patch.progress = Math.max(run.progress, 95);
  } else if (eventType.startsWith('llm_') && run.progress >= 80) {
    if (eventType === 'llm_end') {
      patch.progress = Math.max(run.progress, 96);
    } else if (eventType === 'llm_start') {
      patch.progress = Math.max(run.progress, 88);
    } else {
      patch.progress = Math.max(run.progress, 92);
    }
  }

  return mergePatchAndEstimateEta(run, patch);
}

export const useExecutionStore = create<ExecutionState>((set, get) => ({
  activeRuns: [],
  recentRuns: [],

  startExecution: (params) => {
    const runId = crypto.randomUUID();
    const abortController = new AbortController();
    const sessionId = useStore.getState().sessionId;
    const now = new Date().toISOString();

    const initialRun: ExecutionRun = {
      runId,
      query: params.query,
      tickers: params.tickers ?? [],
      source: params.source,
      outputMode: params.outputMode ?? 'brief',
      analysisDepth: params.analysisDepth,
      status: 'running',
      agentStatuses: {},
      pipelineStages: createInitialPipelineStages(),
      pipelineCurrentStage: null,
      selectedAgents: [],
      skippedAgents: [],
      planSteps: [],
      hasParallelPlan: false,
      reasoningBrief: undefined,
      decisionNotes: [],
      etaSeconds: null,
      progress: 0,
      currentStep: '准备执行...',
      timeline: [],
      report: null,
      streamedContent: '',
      fallbackReasons: [],
      error: null,
      startedAt: now,
      completedAt: null,
      abortController,
      bridgedToChat: false,
      interruptData: null,
    };

    set((state) => ({
      activeRuns: [...state.activeRuns, initialRun],
    }));

    const prefs = getAgentPreferences();
    const override = params.agentPreferencesOverride;
    const requestPrefs = {
      agents: override?.agents ?? prefs.agents,
      maxRounds: override?.maxRounds ?? prefs.maxRounds,
      concurrentMode: override?.concurrentMode ?? prefs.concurrentMode,
    };
    const request: ExecuteRequest = {
      query: params.query,
      tickers: params.tickers,
      output_mode: params.outputMode,
      analysis_depth: params.analysisDepth,
      agents: params.agents,
      budget: params.budget ?? requestPrefs.maxRounds,
      source: params.source,
      session_id: sessionId,
      run_id: runId,
      agent_preferences: requestPrefs,
    };

    const updateRun = (patch: Partial<ExecutionRun>) => {
      set((state) => ({
        activeRuns: state.activeRuns.map((run) =>
          run.runId === runId ? { ...run, ...patch } : run,
        ),
      }));
    };

    const getRun = (): ExecutionRun | undefined =>
      get().activeRuns.find((run) => run.runId === runId);

    const completeRun = (finalPatch: Partial<ExecutionRun>) => {
      const run = getRun();
      if (!run) return;

      const completed: ExecutionRun = {
        ...run,
        ...finalPatch,
        etaSeconds: null,
        completedAt: new Date().toISOString(),
        abortController: null,
      };

      set((state) => ({
        activeRuns: state.activeRuns.filter((item) => item.runId !== runId),
        recentRuns: [completed, ...state.recentRuns].slice(0, MAX_RECENT_RUNS),
      }));
    };

    const callbacks: SSECallbacks = {
      onThinking: (step) => {
        const run = getRun();
        if (!run || run.status !== 'running') return;

        const runIdFromEvent = typeof step?.runId === 'string'
          ? step.runId
          : (typeof step?.result?.run_id === 'string' ? step.result.run_id : undefined);
        if (runIdFromEvent && runIdFromEvent !== runId) return;

        const timeline = pushTimeline(run, buildTimelineEvent(runId, step, runIdFromEvent));
        const patch = pipelineReducer(run, step, timeline);
        updateRun(patch);
      },

      onToken: (token) => {
        const run = getRun();
        if (!run || run.status !== 'running') return;
        const pipelineStages = { ...(run.pipelineStages ?? createInitialPipelineStages()) };
        const timestamp = new Date().toISOString();
        pipelineStages.rendering = {
          ...pipelineStages.rendering,
          status: pipelineStages.rendering.status === 'done' ? 'done' : 'running',
          startedAt: pipelineStages.rendering.startedAt ?? timestamp,
          message: 'Rendering markdown stream',
        };
        updateRun({
          streamedContent: run.streamedContent + token,
          progress: Math.max(run.progress, 92),
          currentStep: '生成报告中...',
          pipelineStages,
          pipelineCurrentStage: run.pipelineCurrentStage ?? 'rendering',
          etaSeconds: run.etaSeconds,
        });
      },

      onDone: (report?: any, _thinking?: any[], meta?: any) => {
        const streamRunId = typeof meta?.run_id === 'string' ? meta.run_id : undefined;
        if (streamRunId && streamRunId !== runId) return;

        const run = getRun();
        const timeline = run
          ? pushTimeline(run, {
              id: `${runId}:${Date.now()}:done`,
              timestamp: new Date().toISOString(),
              eventType: 'done',
              stage: 'done',
              message: 'execution done',
              runId: streamRunId || runId,
              sessionId: typeof meta?.session_id === 'string' ? meta.session_id : undefined,
              raw: (meta && typeof meta === 'object') ? meta : {},
            })
          : [];

        const pipelineStages = run?.pipelineStages
          ? { ...run.pipelineStages }
          : createInitialPipelineStages();
        const doneAt = new Date().toISOString();
        pipelineStages.done = {
          ...pipelineStages.done,
          stage: 'done',
          status: 'done',
          startedAt: pipelineStages.done.startedAt ?? doneAt,
          completedAt: doneAt,
          message: 'Execution completed',
        };
        if (pipelineStages.rendering.status === 'running') {
          pipelineStages.rendering = {
            ...pipelineStages.rendering,
            status: 'done',
            completedAt: doneAt,
          };
        }

        completeRun({
          status: 'done',
          progress: 100,
          currentStep: null,
          report: (report as ReportIR) ?? null,
          timeline,
          pipelineStages,
          pipelineCurrentStage: 'done',
        });
      },

      onError: (error) => {
        const run = getRun();
        const timeline = run
          ? pushTimeline(run, {
              id: `${runId}:${Date.now()}:error`,
              timestamp: new Date().toISOString(),
              eventType: 'error',
              stage: 'error',
              message: error ?? 'Unknown error',
              runId,
            })
          : [];

        completeRun({
          status: 'error',
          error: error ?? 'Unknown error',
          currentStep: null,
          timeline,
        });
      },

      onInterrupt: (data) => {
        const run = getRun();
        const timeline = run
          ? pushTimeline(run, {
              id: `${runId}:${Date.now()}:interrupt`,
              timestamp: new Date().toISOString(),
              eventType: 'interrupt',
              stage: 'interrupt',
              message: data.prompt ?? '等待确认...',
              runId,
              raw: data as unknown as Record<string, unknown>,
            })
          : [];

        updateRun({
          status: 'interrupted',
          currentStep: data.prompt ?? '等待确认...',
          interruptData: data,
          timeline,
          etaSeconds: null,
        });
      },
    };

    callbacks.onRawEvent = (event) => {
      useStore.getState().addRawEvent(event);
    };

    const traceRawEnabled = useStore.getState().traceRawEnabled;
    void (async () => {
      try {
        await apiClient.executeAgent(request, callbacks, {
          signal: abortController.signal,
          traceRawEnabled,
        });

        const run = getRun();
        if (run && run.status === 'running') {
          callbacks.onError?.('Execution stream ended unexpectedly (missing done event)');
        }
      } catch (err: unknown) {
        if (abortController.signal.aborted) return;
        const message = err instanceof Error ? err.message : 'Execution failed';
        callbacks.onError?.(message);
      }
    })();

    return runId;
  },

  beginExternalExecution: (params) => {
    set((state) => {
      const activeIndex = state.activeRuns.findIndex((run) => run.runId === params.runId);
      if (activeIndex >= 0) {
        const activeRuns = [...state.activeRuns];
        const current = activeRuns[activeIndex];
        if (current.status !== 'running') {
          activeRuns[activeIndex] = {
            ...current,
            status: 'running',
            error: null,
            completedAt: null,
            abortController: null,
            interruptData: null,
          };
          return { activeRuns };
        }
        return state;
      }

      const recentIndex = state.recentRuns.findIndex((run) => run.runId === params.runId);
      if (recentIndex >= 0) {
        const recent = state.recentRuns[recentIndex];
        const revived: ExecutionRun = {
          ...recent,
          status: 'running',
          error: null,
          completedAt: null,
          abortController: null,
          interruptData: null,
        };
        const nextRecent = state.recentRuns.filter((_, idx) => idx !== recentIndex);
        return {
          activeRuns: [...state.activeRuns, revived],
          recentRuns: nextRecent,
        };
      }

      const nextRun = createExecutionRunState({
        runId: params.runId,
        query: params.query,
        tickers: params.tickers ?? [],
        source: params.source,
        outputMode: params.outputMode ?? 'brief',
        analysisDepth: params.analysisDepth,
        abortController: null,
      });
      return {
        activeRuns: [...state.activeRuns, nextRun],
      };
    });
  },

  ingestExternalThinking: (runId, step) => {
    set((state) => {
      const index = state.activeRuns.findIndex((run) => run.runId === runId);
      if (index < 0) return state;

      const activeRuns = [...state.activeRuns];
      const current = activeRuns[index];
      const run: ExecutionRun = current.status === 'interrupted'
        ? { ...current, status: 'running' as const, interruptData: null, error: null }
        : current;

      const runIdFromEvent = typeof step?.runId === 'string'
        ? step.runId
        : (typeof step?.result?.run_id === 'string' ? step.result.run_id : undefined);
      if (runIdFromEvent && runIdFromEvent !== runId) return state;

      const timeline = pushTimeline(run, buildTimelineEvent(runId, step, runIdFromEvent));
      const patch = pipelineReducer(run, step, timeline);
      activeRuns[index] = { ...run, ...patch };
      return { activeRuns };
    });
  },

  ingestExternalToken: (runId, token = '') => {
    set((state) => {
      const index = state.activeRuns.findIndex((run) => run.runId === runId);
      if (index < 0) return state;

      const activeRuns = [...state.activeRuns];
      const current = activeRuns[index];
      const run: ExecutionRun = current.status === 'interrupted'
        ? { ...current, status: 'running' as const, interruptData: null, error: null }
        : current;

      const pipelineStages = { ...(run.pipelineStages ?? createInitialPipelineStages()) };
      const timestamp = new Date().toISOString();
      pipelineStages.rendering = {
        ...pipelineStages.rendering,
        status: pipelineStages.rendering.status === 'done' ? 'done' : 'running',
        startedAt: pipelineStages.rendering.startedAt ?? timestamp,
        message: 'Rendering markdown stream',
      };
      const patch = mergePatchAndEstimateEta(run, {
        streamedContent: run.streamedContent + token,
        progress: Math.max(run.progress, 92),
        currentStep: '生成报告中...',
        pipelineStages,
        pipelineCurrentStage: run.pipelineCurrentStage ?? 'rendering',
      });
      activeRuns[index] = { ...run, ...patch };
      return { activeRuns };
    });
  },

  completeExternalExecution: ({ runId, status, report = null, error = null, meta }) => {
    set((state) => {
      const index = state.activeRuns.findIndex((run) => run.runId === runId);
      if (index < 0) return state;

      const activeRuns = [...state.activeRuns];
      const run = activeRuns[index];
      const doneAt = new Date().toISOString();

      let timeline = run.timeline;
      let pipelineStages = run.pipelineStages ?? createInitialPipelineStages();
      let nextCurrentStage = run.pipelineCurrentStage;
      let nextError = error ?? run.error;
      let nextProgress = run.progress;

      if (status === 'done') {
        timeline = pushTimeline(run, {
          id: `${runId}:${Date.now()}:done`,
          timestamp: doneAt,
          eventType: 'done',
          stage: 'done',
          message: 'execution done',
          runId,
          raw: (meta && typeof meta === 'object') ? meta : {},
        });
        pipelineStages = {
          ...pipelineStages,
          done: {
            ...pipelineStages.done,
            stage: 'done',
            status: 'done',
            startedAt: pipelineStages.done.startedAt ?? doneAt,
            completedAt: doneAt,
            message: 'Execution completed',
          },
          rendering: pipelineStages.rendering.status === 'running'
            ? {
                ...pipelineStages.rendering,
                status: 'done',
                completedAt: doneAt,
              }
            : pipelineStages.rendering,
        };
        nextCurrentStage = 'done';
        nextProgress = 100;
      } else if (status === 'error') {
        const message = nextError || 'Unknown error';
        timeline = pushTimeline(run, {
          id: `${runId}:${Date.now()}:error`,
          timestamp: doneAt,
          eventType: 'error',
          stage: 'error',
          message,
          runId,
          raw: (meta && typeof meta === 'object') ? meta : {},
        });
        nextError = message;
      } else {
        timeline = pushTimeline(run, {
          id: `${runId}:${Date.now()}:cancel`,
          timestamp: doneAt,
          eventType: 'cancel',
          stage: 'cancel',
          message: nextError || 'Execution cancelled',
          runId,
          raw: (meta && typeof meta === 'object') ? meta : {},
        });
        nextError = nextError || 'Execution cancelled';
      }

      const completed: ExecutionRun = {
        ...run,
        status,
        report: report ?? run.report,
        error: status === 'done' ? null : nextError,
        progress: nextProgress,
        currentStep: null,
        timeline,
        pipelineStages,
        pipelineCurrentStage: nextCurrentStage,
        etaSeconds: null,
        completedAt: doneAt,
        abortController: null,
        interruptData: null,
      };
      activeRuns.splice(index, 1);
      return {
        activeRuns,
        recentRuns: [completed, ...state.recentRuns].slice(0, MAX_RECENT_RUNS),
      };
    });
  },

  interruptExternalExecution: (runId, data) => {
    set((state) => {
      const index = state.activeRuns.findIndex((run) => run.runId === runId);
      if (index < 0) return state;

      const activeRuns = [...state.activeRuns];
      const run = activeRuns[index];
      const timeline = pushTimeline(run, {
        id: `${runId}:${Date.now()}:interrupt`,
        timestamp: new Date().toISOString(),
        eventType: 'interrupt',
        stage: 'interrupt',
        message: data.prompt ?? 'Waiting for confirmation...',
        runId,
        raw: data as unknown as Record<string, unknown>,
      });
      activeRuns[index] = {
        ...run,
        status: 'interrupted',
        currentStep: data.prompt ?? 'Waiting for confirmation...',
        interruptData: data,
        timeline,
        etaSeconds: null,
      };
      return { activeRuns };
    });
  },

  cancelExecution: (runId) => {
    const run = get().activeRuns.find((item) => item.runId === runId);
    if (!run) return;

    run.abortController?.abort();

    const cancelledRun: ExecutionRun = {
      ...run,
      status: 'cancelled',
      currentStep: null,
      completedAt: new Date().toISOString(),
      abortController: null,
      timeline: [...run.timeline],
      etaSeconds: null,
    };

    set((state) => ({
      activeRuns: state.activeRuns.filter((item) => item.runId !== runId),
      recentRuns: [cancelledRun, ...state.recentRuns].slice(0, MAX_RECENT_RUNS),
    }));
  },

  getActiveRunForTicker: (ticker) => {
    const target = ticker.toUpperCase();
    return get().activeRuns.find((run) =>
      run.tickers.some((symbol) => symbol.toUpperCase() === target),
    );
  },

  markBridged: (runId) => {
    set((state) => ({
      recentRuns: state.recentRuns.map((run) =>
        run.runId === runId ? { ...run, bridgedToChat: true } : run,
      ),
    }));
  },
}));
