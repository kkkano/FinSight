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
  ExecutionRun,
  AgentRunInfo,
  StartExecutionParams,
  TimelineEvent,
} from '../types/execution';
import type { ReportIR } from '../types/index';
import { useStore } from './useStore';

const MAX_RECENT_RUNS = 20;
const MAX_TIMELINE_EVENTS = 300;

interface ExecutionState {
  activeRuns: ExecutionRun[];
  recentRuns: ExecutionRun[];
  startExecution: (params: StartExecutionParams) => string;
  cancelExecution: (runId: string) => void;
  getActiveRunForTicker: (ticker: string) => ExecutionRun | undefined;
  markBridged: (runId: string) => void;
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
  const stage = String(step?.stage || eventType || 'thinking');

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

        const stage = String(step?.stage ?? '');
        const result = step?.result ?? {};
        const message = String(step?.message ?? '');
        const timeline = pushTimeline(run, buildTimelineEvent(runId, step, runIdFromEvent));

        if (stage === 'supervisor_start') {
          const agentNames: string[] = Array.isArray(result.agents) ? result.agents : [];
          const newStatuses: Record<string, AgentRunInfo> = {};
          for (const name of agentNames) {
            newStatuses[name] = { name, status: 'pending' };
          }

          updateRun({
            agentStatuses: { ...run.agentStatuses, ...newStatuses },
            progress: Math.max(run.progress, 5),
            currentStep: message || '协调器启动',
            timeline,
          });
          return;
        }

        if (stage === 'agent_start') {
          const agentName: string | undefined = result.agent;
          if (!agentName) return;

          const latestRun = getRun();
          if (!latestRun) return;

          const statuses = { ...latestRun.agentStatuses };
          if (!statuses[agentName]) {
            statuses[agentName] = { name: agentName, status: 'pending' };
          }
          statuses[agentName] = {
            ...statuses[agentName],
            status: 'running',
            startedAt: new Date().toISOString(),
          };

          updateRun({
            agentStatuses: statuses,
            progress: calculateAgentProgress(statuses, latestRun.progress),
            currentStep: `${agentName} 执行中...`,
            timeline,
          });
          return;
        }

        if (stage === 'agent_done') {
          const agentName: string | undefined = result.agent;
          if (!agentName) return;

          const latestRun = getRun();
          if (!latestRun) return;

          const statuses = { ...latestRun.agentStatuses };
          if (statuses[agentName]) {
            statuses[agentName] = {
              ...statuses[agentName],
              status: 'done',
              completedAt: new Date().toISOString(),
            };
          }

          updateRun({
            agentStatuses: statuses,
            progress: calculateAgentProgress(statuses, latestRun.progress),
            currentStep: `${agentName} 完成`,
            timeline,
          });
          return;
        }

        if (stage === 'agent_error') {
          const agentName: string | undefined = result.agent;
          if (!agentName) return;

          const latestRun = getRun();
          if (!latestRun) return;

          const statuses = { ...latestRun.agentStatuses };
          if (statuses[agentName]) {
            statuses[agentName] = {
              ...statuses[agentName],
              status: 'error',
              error: result.error || 'Unknown error',
              completedAt: new Date().toISOString(),
            };
          }

          const fallbackReasons = [...latestRun.fallbackReasons];
          if (result.error) {
            fallbackReasons.push(`${agentName}: ${result.error}`);
          }

          updateRun({
            agentStatuses: statuses,
            progress: calculateAgentProgress(statuses, latestRun.progress),
            currentStep: `${agentName} 异常`,
            fallbackReasons,
            timeline,
          });
          return;
        }

        const latestRun = getRun() ?? run;
        const patch: Partial<ExecutionRun> = { timeline };
        if (message) patch.currentStep = message;

        const normalizedStage = stage.toLowerCase();
        if (normalizedStage.includes('synth')) {
          patch.progress = Math.max(latestRun.progress, 88);
        } else if (normalizedStage.includes('render')) {
          patch.progress = Math.max(latestRun.progress, 95);
        } else if (normalizedStage.startsWith('llm_') && latestRun.progress >= 80) {
          if (normalizedStage === 'llm_end') {
            patch.progress = Math.max(latestRun.progress, 96);
          } else if (normalizedStage === 'llm_start') {
            patch.progress = Math.max(latestRun.progress, 88);
          } else {
            patch.progress = Math.max(latestRun.progress, 92);
          }
        }
        updateRun(patch);
      },

      onToken: (token) => {
        const run = getRun();
        if (!run || run.status !== 'running') return;
        updateRun({
          streamedContent: run.streamedContent + token,
          progress: Math.max(run.progress, 92),
          currentStep: '生成报告中...',
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

        completeRun({
          status: 'done',
          progress: 100,
          currentStep: null,
          report: (report as ReportIR) ?? null,
          timeline,
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
