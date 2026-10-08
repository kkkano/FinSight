import { useQuery } from '@tanstack/react-query';

import { apiClient } from '../api/client';
import {
  toPredictionFailure,
  type PredictionFailure,
} from '../api/domains/predictions';
import { useStore } from '../store/useStore';

export interface PredictionHistoryOptions {
  /** Disable network reads for anonymous surfaces such as Today. */
  enabled?: boolean;
  limit?: number;
}

export function usePredictionHistory(options: PredictionHistoryOptions = {}) {
  const enabled = options.enabled ?? true;
  const limit = options.limit ?? 100;
  const owner = useStore((state) => state.authIdentity?.userId);
  const history = useQuery({
    queryKey: ['predictions', owner || 'anonymous', 'history', limit],
    queryFn: ({ signal }) => apiClient.getPredictionHistory({ limit }, signal),
    enabled: enabled && Boolean(owner), retry: false,
  });
  const stats = useQuery({
    queryKey: ['predictions', owner || 'anonymous', 'stats', 90],
    queryFn: ({ signal }) => apiClient.getPredictionStats({ days: 90 }, signal),
    enabled: enabled && Boolean(owner), retry: false,
  });
  const error = history.error ?? stats.error;
  const refresh = () => { void history.refetch(); void stats.refetch(); };
  return {
    items: owner && enabled ? history.data?.items ?? [] : [],
    stats: owner && enabled ? stats.data?.stats ?? null : null,
    loading: history.isLoading || stats.isLoading,
    failure: error ? toPredictionFailure(error) : null,
    refresh,
  };
}

export function usePredictionRunState(runId: string | null | undefined) {
  const owner = useStore((state) => state.authIdentity?.userId);
  const normalized = String(runId || '').trim();
  const query = useQuery({
    queryKey: ['predictions', owner || 'anonymous', 'run', normalized],
    queryFn: ({ signal }) => apiClient.getPredictionRun(normalized, signal),
    enabled: Boolean(owner && normalized), retry: false,
  });
  const failure: PredictionFailure | null = query.error ? toPredictionFailure(query.error) : null;
  return { run: owner ? query.data ?? null : null, loading: query.isLoading, failure, refresh: () => { void query.refetch(); } };
}

export function usePredictionRun(runId: string | null | undefined) {
  return usePredictionRunState(runId).run;
}
