import { useCallback, useEffect } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { buildApiUrl } from '../config/runtime';
import { useDashboardStore } from '../store/dashboardStore';
import type { DashboardResponse } from '../types/dashboard';

const dashboardQueryKey = (symbol: string) => ['dashboard', symbol] as const;

const fetchDashboard = async (symbol: string, signal?: AbortSignal): Promise<DashboardResponse> => {
  const response = await fetch(buildApiUrl(`/api/dashboard?symbol=${encodeURIComponent(symbol)}`), { signal });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(payload?.detail?.message || payload?.message || `HTTP ${response.status}`);
  }
  return response.json() as Promise<DashboardResponse>;
};

export function useDashboardData(symbol: string | null, enabled = true) {
  const client = useQueryClient();
  const setActiveAsset = useDashboardStore((state) => state.setActiveAsset);
  const query = useQuery({
    queryKey: dashboardQueryKey(symbol || ''),
    queryFn: ({ signal }) => fetchDashboard(symbol!, signal),
    enabled: enabled && Boolean(symbol),
  });
  useEffect(() => {
    if (enabled && query.data) setActiveAsset(query.data.state.active_asset);
  }, [enabled, query.data, setActiveAsset]);
  const refetch = useCallback(async (nextSymbol: string) => {
    const normalized = nextSymbol.trim();
    if (!normalized) return;
    await client.invalidateQueries({ queryKey: dashboardQueryKey(normalized), exact: true });
  }, [client]);
  return {
    refetch, dashboardData: query.data?.data ?? null,
    capabilities: query.data?.state.capabilities ?? null,
    isLoading: query.isFetching, error: query.error instanceof Error ? query.error.message : null,
  };
}

export function useDashboardSnapshot() {
  const symbol = useDashboardStore((state) => state.activeAsset?.symbol ?? null);
  return useDashboardData(symbol, false).dashboardData;
}
