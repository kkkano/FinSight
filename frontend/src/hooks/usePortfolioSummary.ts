import { useCallback, useEffect, useState } from 'react';
import { apiClient, type PortfolioSummaryResponse } from '../api/client';

interface UsePortfolioSummaryResult {
  data: PortfolioSummaryResponse | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export function usePortfolioSummary(sessionId: string | null | undefined): UsePortfolioSummaryResult {
  const [data, setData] = useState<PortfolioSummaryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!sessionId) {
      setData(null);
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const payload = await apiClient.getPortfolioSummary(sessionId);
      setData(payload);
    } catch (err) {
      setData(null);
      setError(err instanceof Error ? err.message : 'Failed to load portfolio summary');
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => {
      void refresh();
    }, 60_000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  return { data, loading, error, refresh };
}
