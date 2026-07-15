import { useCallback, useEffect, useRef, useState } from 'react';

import {
  describePredictionFailure,
  toPredictionFailure,
  type PredictionFailure,
  type PredictionRunView,
} from '../api/domains/predictions';
import { apiClient } from '../api/client';

export const PREDICTION_POLL_INTERVAL_MS = 1_500;
export const PREDICTION_POLL_BUDGET_MS = 75_000;

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
    const timer = window.setTimeout(resolve, milliseconds);
    signal?.addEventListener('abort', () => {
      window.clearTimeout(timer);
      reject(abortError());
    }, { once: true });
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
  onSucceededRef.current = onSucceeded;

  const reset = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    setState(INITIAL_STATE);
  }, []);

  useEffect(() => reset, [reset, symbol]);

  const generate = useCallback(async () => {
    const normalizedSymbol = symbol.trim().toUpperCase();
    if (!normalizedSymbol) return null;

    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setState({ phase: 'submitting', run: null, failure: null });

    try {
      const created = await apiClient.generatePrediction(normalizedSymbol, controller.signal);
      if (controller.signal.aborted) return null;

      setState({
        phase: TERMINAL_STATUSES.has(created.run.status) ? 'submitting' : 'polling',
        run: created.run,
        failure: null,
      });
      const run = await pollPredictionRun(created.run, { signal: controller.signal });
      if (controller.signal.aborted) return null;

      if (!TERMINAL_STATUSES.has(run.status)) {
        setState({
          phase: 'timed_out',
          run,
          failure: {
            code: 'prediction_status_timeout',
            message: '生成任务仍在后台运行，请稍后刷新查看结果。',
            status: null,
          },
        });
        return run;
      }

      if (run.status === 'succeeded' && run.prediction_id) {
        setState({ phase: 'succeeded', run, failure: null });
        onSucceededRef.current?.(run.prediction_id);
        return run;
      }

      setState({
        phase: 'failed',
        run,
        failure: describePredictionFailure(run.failure_code, run.failure_detail),
      });
      return run;
    } catch (error) {
      if (controller.signal.aborted) return null;
      setState({ phase: 'failed', run: null, failure: toPredictionFailure(error) });
      return null;
    }
  }, [symbol]);

  return {
    ...state,
    generate,
    reset,
    isGenerating: state.phase === 'submitting' || state.phase === 'polling',
  };
}
