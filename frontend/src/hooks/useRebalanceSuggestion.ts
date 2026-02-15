/**
 * useRebalanceSuggestion — hook for generating and managing rebalance suggestions.
 *
 * Wraps the rebalance API endpoints and provides local state management
 * for the current suggestion lifecycle.
 */
import { useState, useCallback } from 'react';

import { apiClient } from '../api/client.ts';
import type {
  RebalanceSuggestion,
  GenerateRebalanceParams,
  SuggestionStatus,
} from '../types/dashboard.ts';

export function useRebalanceSuggestion() {
  const [suggestion, setSuggestion] = useState<RebalanceSuggestion | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const generate = useCallback(async (params: GenerateRebalanceParams) => {
    setLoading(true);
    setError(null);
    try {
      const result = await apiClient.generateRebalanceSuggestion(
        params as unknown as Record<string, unknown>,
      );
      setSuggestion(result as RebalanceSuggestion);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Generation failed';
      setError(message);
    } finally {
      setLoading(false);
    }
  }, []);

  const updateStatus = useCallback(
    async (suggestionId: string, status: SuggestionStatus) => {
      await apiClient.patchRebalanceSuggestion(suggestionId, { status });
      setSuggestion((prev) => {
        if (!prev || prev.suggestion_id !== suggestionId) return prev;
        return { ...prev, status };
      });
    },
    [],
  );

  const clear = useCallback(() => {
    setSuggestion(null);
    setError(null);
  }, []);

  return { suggestion, loading, error, generate, updateStatus, clear } as const;
}
