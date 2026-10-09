import { createContext, useCallback, useContext } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { buildApiUrl } from '../config/runtime';
import type { ActiveAsset, DashboardData, DashboardResponse } from '../types/dashboard';

export const DashboardContext = createContext<{ asset: ActiveAsset; data: DashboardData | null } | null>(null);

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
  const query = useQuery({
    queryKey: dashboardQueryKey(symbol || ''),
    queryFn: ({ signal }) => fetchDashboard(symbol!, signal),
    enabled: enabled && Boolean(symbol),
  });
  const refetch = useCallback(async (nextSymbol: string) => {
    const normalized = nextSymbol.trim();
    if (!normalized) return;
    await client.invalidateQueries({ queryKey: dashboardQueryKey(normalized), exact: true });
  }, [client]);
  return {
    refetch, dashboardData: query.data?.data ?? null,
    capabilities: query.data?.state.capabilities ?? null,
    asset: query.data?.state.active_asset ?? null,
    isLoading: query.isFetching, error: query.error instanceof Error ? query.error.message : null,
  };
}

export function useDashboardSnapshot() {
  return useContext(DashboardContext)?.data ?? null;
}

export function useDashboardAsset() {
  return useContext(DashboardContext)?.asset ?? null;
}
