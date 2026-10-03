import { useCallback, useEffect, useState } from 'react';

import { apiClient } from '../api/client';
import {
  toPredictionFailure,
  type PredictionFailure,
  type PredictionHistoryItem,
  type PredictionRunView,
  type PredictionStatsResponse,
} from '../api/domains/predictions';

export interface PredictionHistoryOptions {
  /** Disable network reads for anonymous surfaces such as Today. */
  enabled?: boolean;
  limit?: number;
}

export function usePredictionHistory(options: PredictionHistoryOptions = {}) {
  const enabled = options.enabled ?? true;
  const limit = options.limit ?? 100;
  const [items, setItems] = useState<PredictionHistoryItem[]>([]);
  const [stats, setStats] = useState<PredictionStatsResponse['stats'] | null>(null);
  const [loading, setLoading] = useState(true);
  const [failure, setFailure] = useState<PredictionFailure | null>(null);
  const [requestKey, setRequestKey] = useState(0);

  const refresh = useCallback(() => setRequestKey((value) => value + 1), []);

  useEffect(() => {
    if (!enabled) {
      setItems([]);
      setStats(null);
      setFailure(null);
      setLoading(false);
      return undefined;
    }

    const controller = new AbortController();
    setLoading(true);
    setFailure(null);

    void Promise.all([
      apiClient.getPredictionHistory({ limit }, controller.signal),
      apiClient.getPredictionStats({ days: 90 }, controller.signal),
    ]).then(([history, statsResponse]) => {
      if (controller.signal.aborted) return;
      setItems(history.items);
      setStats(statsResponse.stats);
    }).catch((error) => {
      if (!controller.signal.aborted) setFailure(toPredictionFailure(error));
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });

    return () => controller.abort();
  }, [enabled, limit, requestKey]);

  return { items, stats, loading, failure, refresh };
}

export function usePredictionRunState(runId: string | null | undefined) {
  const [run, setRun] = useState<PredictionRunView | null>(null);
  const [loading, setLoading] = useState(false);
  const [failure, setFailure] = useState<PredictionFailure | null>(null);
  const [requestKey, setRequestKey] = useState(0);
  const refresh = useCallback(() => setRequestKey((value) => value + 1), []);

  useEffect(() => {
    const normalized = String(runId || '').trim();
    if (!normalized) {
      setRun(null);
      setLoading(false);
      setFailure(null);
      return undefined;
    }
    const controller = new AbortController();
    setRun(null);
    setLoading(true);
    setFailure(null);
    void apiClient.getPredictionRun(normalized, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setRun(value);
      })
      .catch((error) => {
        if (!controller.signal.aborted) setFailure(toPredictionFailure(error));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [runId, requestKey]);

  return { run, loading, failure, refresh };
}

export function usePredictionRun(runId: string | null | undefined) {
  return usePredictionRunState(runId).run;
}
