/**
 * ExecutionStore — global Zustand store for agent execution state.
 *
 * Manages active and recent runs, provides event-driven progress
 * tracking from SSE events, and supports cancellation.
 *
 * Contracts (see docs/AGENTIC_SPRINT_TODOLIST.md P1-1a):
 * - runId lifecycle: created in startExecution, immutable until completion
 * - Progress is monotonically increasing (never decreases)
 * - Terminal states (done/error/cancelled) move runs to recentRuns
 * - cancelOnUnmount defaults to false (page navigation won't kill tasks)
 */
import { create } from 'zustand';

import { apiClient } from '../api/client';
import type { ExecuteRequest, SSECallbacks } from '../api/client';
import { getAgentPreferences } from '../components/settings/AgentControlPanel';
import type {
  ExecutionRun,
  AgentRunInfo,
  StartExecutionParams,
} from '../types/execution';
import type { ReportIR } from '../types/index';
import { useStore } from './useStore';

const MAX_RECENT_RUNS = 20;

// --- Store interface ---

interface ExecutionState {
  activeRuns: ExecutionRun[];
  recentRuns: ExecutionRun[];

  startExecution: (params: StartExecutionParams) => string;
  cancelExecution: (runId: string) => void;
  getActiveRunForTicker: (ticker: string) => ExecutionRun | undefined;
  /** Mark a run as bridged to chat (prevents duplicate injection). */
  markBridged: (runId: string) => void;
}

// --- Progress calculation (event-driven, monotonically increasing) ---

function calculateAgentProgress(
  agentStatuses: Record<string, AgentRunInfo>,
  currentProgress: number,
): number {
  const agents = Object.values(agentStatuses);
  const total = Math.max(agents.length, 1);
  const completed = agents.filter(
    (a) => a.status === 'done' || a.status === 'error',
  ).length;
  const calculated = 10 + Math.round((completed / total) * 70);
  return Math.max(currentProgress, calculated);
}

// --- Store ---

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
      status: 'running',
      agentStatuses: {},
      progress: 0,
      currentStep: '准备中...',
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

    // Build API request body (camelCase → snake_case)
    const prefs = getAgentPreferences();
    const request: ExecuteRequest = {
      query: params.query,
      tickers: params.tickers,
      output_mode: params.outputMode,
      agents: params.agents,
      budget: params.budget ?? prefs.maxRounds,
      source: params.source,
      session_id: sessionId,
      agent_preferences: {
        agents: prefs.agents,
        maxRounds: prefs.maxRounds,
        concurrentMode: prefs.concurrentMode,
      },
    };

    // --- Helpers scoped to this run ---

    const updateRun = (patch: Partial<ExecutionRun>) => {
      set((state) => ({
        activeRuns: state.activeRuns.map((r) =>
          r.runId === runId ? { ...r, ...patch } : r,
        ),
      }));
    };

    const getRun = (): ExecutionRun | undefined =>
      get().activeRuns.find((r) => r.runId === runId);

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
        activeRuns: state.activeRuns.filter((r) => r.runId !== runId),
        recentRuns: [completed, ...state.recentRuns].slice(0, MAX_RECENT_RUNS),
      }));
    };

    // --- SSE Callbacks ---

    const callbacks: SSECallbacks = {
      onThinking: (step) => {
        const run = getRun();
        if (!run || run.status !== 'running') return;

        const stage: string = step?.stage ?? '';
        const result = step?.result ?? {};
        const message: string = step?.message ?? '';

        if (stage === 'supervisor_start') {
          // Initialize known agents from event payload
          const agentNames: string[] = Array.isArray(result.agents)
            ? result.agents
            : [];
          const newStatuses: Record<string, AgentRunInfo> = {};
          for (const name of agentNames) {
            newStatuses[name] = { name, status: 'pending' };
          }
          updateRun({
            agentStatuses: { ...run.agentStatuses, ...newStatuses },
            progress: Math.max(run.progress, 5),
            currentStep: message || '协调器启动',
          });
        } else if (stage === 'agent_start') {
          const agentName: string | undefined = result.agent;
          if (!agentName) return;

          const latestRun = getRun();
          if (!latestRun) return;

          const statuses = { ...latestRun.agentStatuses };
          // Dynamic append if not listed in supervisor_start
          if (!statuses[agentName]) {
            statuses[agentName] = { name: agentName, status: 'pending' };
          }
          statuses[agentName] = {
            ...statuses[agentName],
            status: 'running',
            startedAt: new Date().toISOString(),
          };

          const progress = calculateAgentProgress(statuses, latestRun.progress);
          updateRun({
            agentStatuses: statuses,
            progress,
            currentStep: `${agentName} 执行中...`,
          });
        } else if (stage === 'agent_done') {
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

          const progress = calculateAgentProgress(statuses, latestRun.progress);
          updateRun({
            agentStatuses: statuses,
            progress,
            currentStep: `${agentName} 完成`,
          });
        } else if (stage === 'agent_error') {
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

          const progress = calculateAgentProgress(statuses, latestRun.progress);
          const fallbackReasons = [...latestRun.fallbackReasons];
          if (result.error) {
            fallbackReasons.push(`${agentName}: ${result.error}`);
          }

          updateRun({
            agentStatuses: statuses,
            progress,
            currentStep: `${agentName} 异常`,
            fallbackReasons,
          });
        } else {
          // Generic thinking step — update currentStep only
          const latestRun = getRun() ?? run;
          const patch: Partial<ExecutionRun> = {};
          if (message) {
            patch.currentStep = message;
          }
          const normalizedStage = String(stage || '').toLowerCase();
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
          if (Object.keys(patch).length > 0) {
            updateRun(patch);
          }
        }
      },

      onToken: (token) => {
        const run = getRun();
        if (!run || run.status !== 'running') return;

        updateRun({
          streamedContent: run.streamedContent + token,
          progress: Math.max(run.progress, 92),
          currentStep: '生成报告...',
        });
      },

      onDone: (report?: any) => {
        completeRun({
          status: 'done',
          progress: 100,
          currentStep: null,
          report: (report as ReportIR) ?? null,
        });
      },

      onError: (error) => {
        completeRun({
          status: 'error',
          error: error ?? 'Unknown error',
          currentStep: null,
        });
      },

      onInterrupt: (data) => {
        updateRun({
          status: 'interrupted',
          currentStep: data.prompt ?? '等待确认...',
          interruptData: data,
        });
      },
    };

    // Fire-and-forget — errors handled via onError callback
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
        const msg = err instanceof Error ? err.message : 'Execution failed';
        callbacks.onError?.(msg);
      }
    })();

    return runId;
  },

  cancelExecution: (runId) => {
    const run = get().activeRuns.find((r) => r.runId === runId);
    if (!run) return;

    run.abortController?.abort();

    const cancelledRun: ExecutionRun = {
      ...run,
      status: 'cancelled',
      currentStep: null,
      completedAt: new Date().toISOString(),
      abortController: null,
    };

    set((state) => ({
      activeRuns: state.activeRuns.filter((r) => r.runId !== runId),
      recentRuns: [cancelledRun, ...state.recentRuns].slice(0, MAX_RECENT_RUNS),
    }));
  },

  getActiveRunForTicker: (ticker) => {
    const upper = ticker.toUpperCase();
    return get().activeRuns.find((r) =>
      r.tickers.some((t) => t.toUpperCase() === upper),
    );
  },

  markBridged: (runId) => {
    set((state) => ({
      recentRuns: state.recentRuns.map((r) =>
        r.runId === runId ? { ...r, bridgedToChat: true } : r,
      ),
    }));
  },
}));
