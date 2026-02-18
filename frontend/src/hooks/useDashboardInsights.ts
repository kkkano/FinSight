/**
 * Dashboard AI Insights Hook (Phase F)
 *
 * Fetches AI insight cards from /api/dashboard/insights.
 * Parallel to useDashboardData — abort on symbol change,
 * stale-while-revalidate support.
 */
import { useEffect, useRef, useCallback } from 'react';
import { useDashboardStore } from '../store/dashboardStore';
import { apiClient } from '../api/client';

export function useDashboardInsights(symbol: string | null) {
  const {
    setInsightsData,
    setInsightsLoading,
    setInsightsError,
    setInsightsStale,
    setInsightsCachedAt,
  } = useDashboardStore();

  const abortRef = useRef<AbortController | null>(null);

  const fetchInsights = useCallback(
    async (sym: string, opts?: { force?: boolean }) => {
      // Abort previous request
      if (abortRef.current) {
        abortRef.current.abort();
      }
      const controller = new AbortController();
      abortRef.current = controller;

      setInsightsLoading(true);
      setInsightsError(null);

      try {
        const json = await apiClient.getDashboardInsights(sym, {
          force: opts?.force,
          signal: controller.signal,
        });

        // Only update state if request was not aborted
        if (!controller.signal.aborted) {
          setInsightsData(json.insights);
          setInsightsStale(json.cached && json.cache_age_seconds > 3600);
          setInsightsCachedAt(json.generated_at || null);
        }
      } catch (err: unknown) {
        if (err instanceof Error && err.name !== 'AbortError') {
          setInsightsError(err.message || 'Failed to load AI insights');
        }
      } finally {
        if (!controller.signal.aborted) {
          setInsightsLoading(false);
        }
      }
    },
    [
      setInsightsData,
      setInsightsLoading,
      setInsightsError,
      setInsightsStale,
      setInsightsCachedAt,
    ],
  );

  // Auto-fetch when symbol changes
  useEffect(() => {
    if (symbol) {
      fetchInsights(symbol);
    }
    return () => {
      abortRef.current?.abort();
    };
  }, [symbol, fetchInsights]);

  return { refetch: fetchInsights };
}
