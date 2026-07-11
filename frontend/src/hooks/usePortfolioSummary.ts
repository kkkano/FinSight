import { useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';

import { apiClient, type PortfolioSummaryResponse } from '../api/client';

interface UsePortfolioSummaryResult {
  data: PortfolioSummaryResponse | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

const POLL_INTERVAL_MS = 60_000;

export function usePortfolioSummary(sessionId: string | null | undefined): UsePortfolioSummaryResult {
  const sid = String(sessionId || '').trim();
  const query = useQuery({
    queryKey: ['portfolio-summary', sid],
    queryFn: () => apiClient.getPortfolioSummary(sid),
    enabled: Boolean(sid),
    refetchInterval: POLL_INTERVAL_MS,
  });
  const {
    data,
    error: queryError,
    isFetching,
    refetch: refetchQuery,
  } = query;

  const refresh = useCallback(async () => {
    if (!sid) return;
    await refetchQuery();
  }, [refetchQuery, sid]);

  const error = queryError instanceof Error ? queryError.message : null;

  return { data: data ?? null, loading: isFetching, error, refresh };
}

/** 从 summary 数据构建 {ticker: shares} 快查表（旧组件迁移用） */
export function buildPositionsMap(data: PortfolioSummaryResponse | null): Record<string, number> {
  if (!data || !Array.isArray(data.positions)) return {};
  return data.positions.reduce<Record<string, number>>((acc, pos) => {
    const ticker = String(pos?.ticker || '').trim().toUpperCase();
    const shares = Number(pos?.shares);
    if (ticker && Number.isFinite(shares) && shares > 0) {
      acc[ticker] = shares;
    }
    return acc;
  }, {});
}
