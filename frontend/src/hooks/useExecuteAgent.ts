/**
 * useExecuteAgent — React hook for triggering agent executions.
 *
 * Wraps `useExecutionStore` and provides a component-friendly interface.
 *
 * Key design decision: `cancelOnUnmount` defaults to **false** so that
 * page navigation does NOT kill running tasks.
 */
import { useCallback, useEffect, useRef, useState } from 'react';

import { useExecutionStore } from '../store/executionStore';
import type { StartExecutionParams } from '../types/execution';
import type { ReportIR } from '../types/index';

// --- Options ---

interface UseExecuteAgentOptions {
  onComplete?: (report: ReportIR | null) => void;
  onError?: (error: string) => void;
  /** Default false — unmounting the component will NOT cancel the run. */
  cancelOnUnmount?: boolean;
}

// --- Return type ---

interface UseExecuteAgentReturn {
  /** Start execution and return the runId. */
  execute: (params: StartExecutionParams) => string;
  isRunning: boolean;
  progress: number;
  currentStep: string | null;
  result: ReportIR | null;
  error: string | null;
  cancel: () => void;
  runId: string | null;
}

// --- Hook ---

export function useExecuteAgent(
  options: UseExecuteAgentOptions = {},
): UseExecuteAgentReturn {
  const { onComplete, onError, cancelOnUnmount = false } = options;

  const runIdRef = useRef<string | null>(null);
  const [currentRunId, setCurrentRunId] = useState<string | null>(null);

  const startExecution = useExecutionStore((s) => s.startExecution);
  const cancelExecution = useExecutionStore((s) => s.cancelExecution);

  // Subscribe to the specific run's state (active or recent)
  const run = useExecutionStore((s) => {
    if (!currentRunId) return null;
    return (
      s.activeRuns.find((r) => r.runId === currentRunId) ??
      s.recentRuns.find((r) => r.runId === currentRunId) ??
      null
    );
  });

  const execute = useCallback(
    (params: StartExecutionParams): string => {
      const id = startExecution(params);
      runIdRef.current = id;
      setCurrentRunId(id);
      return id;
    },
    [startExecution],
  );

  const cancel = useCallback(() => {
    if (runIdRef.current) {
      cancelExecution(runIdRef.current);
    }
  }, [cancelExecution]);

  // Trigger onComplete / onError callbacks on terminal status change
  const prevStatusRef = useRef<string | null>(null);
  useEffect(() => {
    if (!run) return;
    if (run.status === prevStatusRef.current) return;
    prevStatusRef.current = run.status;

    if (run.status === 'done') {
      onComplete?.(run.report);
    } else if (run.status === 'error' && run.error) {
      onError?.(run.error);
    }
  }, [run, onComplete, onError]);

  // Cancel on unmount — ONLY if explicitly opted-in
  useEffect(() => {
    return () => {
      if (!cancelOnUnmount || !runIdRef.current) return;

      const store = useExecutionStore.getState();
      const active = store.activeRuns.find(
        (r) => r.runId === runIdRef.current,
      );
      if (active) {
        store.cancelExecution(runIdRef.current);
      }
    };
  }, [cancelOnUnmount]);

  return {
    execute,
    isRunning: run?.status === 'running',
    progress: run?.progress ?? 0,
    currentStep: run?.currentStep ?? null,
    result: run?.report ?? null,
    error: run?.error ?? null,
    cancel,
    runId: currentRunId,
  };
}
