/**
 * usePortfolioData — hook for fetching portfolio summary from the API.
 *
 * Auto-fetches on mount and refreshes every 60 seconds while the
 * component is mounted. Relies on sessionId from the global store.
 */
import { useState, useEffect, useCallback } from 'react';

import { apiClient } from '../api/client.ts';
import { useStore } from '../store/useStore.ts';

export interface PortfolioSummary {
  total_value: number;
  total_cost: number;
  total_pnl: number;
  total_pnl_pct: number;
  position_count: number;
  positions: { ticker: string; shares: number; weight: number; market_value: number }[];
}

const REFRESH_INTERVAL_MS = 60_000;

export function usePortfolioData() {
  const sessionId = useStore((s) => s.sessionId);
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    if (!sessionId) return;
    setLoading(true);
    try {
      const data = await apiClient.getPortfolioSummary(sessionId);
      setSummary(data as PortfolioSummary);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to load portfolio';
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    refetch();
  }, [refetch]);

  // Auto-refresh on interval
  useEffect(() => {
    const interval = setInterval(refetch, REFRESH_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [refetch]);

  return { summary, loading, error, refetch } as const;
}
