import { useCallback, useEffect, useRef, useState } from 'react';

import {
  describePredictionFailure,
  toPredictionFailure,
  type PredictionFailure,
  type PredictionRunView,
} from '../api/domains/predictions';
import { apiClient } from '../api/client';
import { useStore } from '../store/useStore';

export const PREDICTION_POLL_INTERVAL_MS = 1_500;
export const PREDICTION_POLL_BUDGET_MS = 185_000;

const TERMINAL_STATUSES = new Set<PredictionRunView['status']>([
  'succeeded',
  'unavailable',
  'failed',
  'cancelled',
]);

type PollOptions = {
  signal?: AbortSignal;
  intervalMs?: number;
  budgetMs?: number;
  now?: () => number;
  sleep?: (milliseconds: number, signal?: AbortSignal) => Promise<void>;
  getRun?: (runId: string, signal?: AbortSignal) => Promise<PredictionRunView>;
};

function abortError(): DOMException {
  return new DOMException('Prediction polling aborted', 'AbortError');
}

export function predictionPollDelay(milliseconds: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(abortError());
      return;
    }
    const onAbort = () => {
      window.clearTimeout(timer);
      reject(abortError());
    };
    const timer = window.setTimeout(() => {
      signal?.removeEventListener('abort', onAbort);
      resolve();
    }, milliseconds);
    signal?.addEventListener('abort', onAbort, { once: true });
  });
}

export async function pollPredictionRun(
  initialRun: PredictionRunView,
  options: PollOptions = {},
): Promise<PredictionRunView> {
  if (TERMINAL_STATUSES.has(initialRun.status)) return initialRun;

  const now = options.now ?? Date.now;
  const sleep = options.sleep ?? predictionPollDelay;
  const getRun = options.getRun ?? apiClient.getPredictionRun;
  const deadline = now() + (options.budgetMs ?? PREDICTION_POLL_BUDGET_MS);
  let current = initialRun;

  while (now() < deadline) {
    if (options.signal?.aborted) throw abortError();
    await sleep(options.intervalMs ?? PREDICTION_POLL_INTERVAL_MS, options.signal);
    current = await getRun(initialRun.id, options.signal);
    if (TERMINAL_STATUSES.has(current.status)) return current;
  }

  return current;
}

export type PredictionGenerationState = {
  phase: 'idle' | 'submitting' | 'polling' | 'succeeded' | 'failed' | 'timed_out';
  run: PredictionRunView | null;
  failure: PredictionFailure | null;
};

const INITIAL_STATE: PredictionGenerationState = {
  phase: 'idle',
  run: null,
  failure: null,
};

export function usePredictionGeneration(
  symbol: string,
  onSucceeded?: (predictionId: string) => void,
) {
  const [state, setState] = useState<PredictionGenerationState>(INITIAL_STATE);
  const controllerRef = useRef<AbortController | null>(null);
  const onSucceededRef = useRef(onSucceeded);
  const userId = useStore((store) => store.authIdentity?.userId);
  const normalizedSymbol = symbol.trim().toUpperCase();
  const storageKey = `finsight:prediction-run:${userId || 'anonymous'}:${normalizedSymbol}`;

  useEffect(() => {
    onSucceededRef.current = onSucceeded;
  }, [onSucceeded]);

  const reset = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    setState(INITIAL_STATE);
  }, []);

  const rememberRun = useCallback((run: PredictionRunView) => {
    try {
      if (TERMINAL_STATUSES.has(run.status)) localStorage.removeItem(storageKey);
      else localStorage.setItem(storageKey, run.id);
    } catch {
      // 存储不可用时仍可以在当前页面追踪该运行。
    }
  }, [storageKey]);

  const followRun = useCallback(async (initialRun: PredictionRunView, controller: AbortController) => {
    rememberRun(initialRun);
    setState({ phase: 'polling', run: initialRun, failure: null });
    const run = await pollPredictionRun(initialRun, { signal: controller.signal });
    if (controller.signal.aborted) return null;
    rememberRun(run);
    if (!TERMINAL_STATUSES.has(run.status)) {
      setState({ phase: 'timed_out', run, failure: {
        code: 'prediction_status_timeout', message: '暂未取得运行终态，可刷新继续查看本次任务。', status: null,
      } });
    } else if (run.status === 'succeeded' && run.prediction_id) {
      setState({ phase: 'succeeded', run, failure: null });
      onSucceededRef.current?.(run.prediction_id);
    } else {
      setState({ phase: 'failed', run, failure: describePredictionFailure(run.failure_code, run.failure_detail) });
    }
    return run;
  }, [rememberRun]);

  const resume = useCallback(async () => {
    let runId: string | null = null;
    try { runId = localStorage.getItem(storageKey); } catch { return null; }
    if (!runId || !userId) return null;
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    try {
      const run = await apiClient.getPredictionRun(runId, controller.signal);
      if (controller.signal.aborted) return null;
      return await followRun(run, controller);
    } catch (error) {
      if (!controller.signal.aborted) setState((previous) => ({ ...previous, phase: 'failed', failure: toPredictionFailure(error) }));
      return null;
    }
  }, [followRun, storageKey, userId]);

  useEffect(() => {
    reset();
    void resume();
    return reset;
  }, [reset, resume]);

  const generate = useCallback(async () => {
    if (!normalizedSymbol) return null;

    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setState({ phase: 'submitting', run: null, failure: null });

    try {
      const created = await apiClient.generatePrediction(normalizedSymbol, controller.signal);
      if (controller.signal.aborted) return null;

      return await followRun(created.run, controller);
    } catch (error) {
      if (controller.signal.aborted) return null;
      setState((previous) => ({ ...previous, phase: 'failed', failure: toPredictionFailure(error) }));
      return null;
    }
  }, [normalizedSymbol, followRun]);

  return {
    ...state,
    generate,
    resume,
    reset,
    isGenerating: state.phase === 'submitting' || state.phase === 'polling',
  };
}
