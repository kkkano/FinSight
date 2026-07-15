import { useCallback, useEffect, useState } from 'react';

import { apiClient } from '../api/client';
import {
  toPredictionFailure,
  type PredictionFailure,
  type PredictionHistoryItem,
  type PredictionRunView,
  type PredictionStatsResponse,
} from '../api/domains/predictions';

export function usePredictionHistory() {
  const [items, setItems] = useState<PredictionHistoryItem[]>([]);
  const [stats, setStats] = useState<PredictionStatsResponse['stats'] | null>(null);
  const [loading, setLoading] = useState(true);
  const [failure, setFailure] = useState<PredictionFailure | null>(null);
  const [requestKey, setRequestKey] = useState(0);

  const refresh = useCallback(() => setRequestKey((value) => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setFailure(null);

    void Promise.all([
      apiClient.getPredictionHistory({ limit: 100 }, controller.signal),
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
  }, [requestKey]);

  return { items, stats, loading, failure, refresh };
}

export function usePredictionRun(runId: string | null | undefined) {
  const [run, setRun] = useState<PredictionRunView | null>(null);

  useEffect(() => {
    const normalized = String(runId || '').trim();
    if (!normalized) {
      setRun(null);
      return undefined;
    }
    const controller = new AbortController();
    setRun(null);
    void apiClient.getPredictionRun(normalized, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setRun(value);
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, [runId]);

  return run;
}
