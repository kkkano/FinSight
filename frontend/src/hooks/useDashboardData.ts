/**
 * Dashboard 数据加载 Hook
 *
 * 通过 React Query 统一请求去重、取消与缓存，并同步既有 dashboard store 合同。
 */
import { useCallback, useEffect } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { buildApiUrl } from '../config/runtime';
import { useDashboardStore } from '../store/dashboardStore';
import type { DashboardResponse } from '../types/dashboard';

const dashboardQueryKey = (symbol: string) => ['dashboard', symbol] as const;

const fetchDashboard = async (symbol: string, signal?: AbortSignal): Promise<DashboardResponse> => {
  const response = await fetch(buildApiUrl(`/api/dashboard?symbol=${encodeURIComponent(symbol)}`), { signal });
  if (!response.ok) {
    const errorPayload = await response.json().catch(() => ({ message: 'Unknown error' }));
    throw new Error(errorPayload?.detail?.message || errorPayload?.message || `HTTP ${response.status}`);
  }
  return response.json() as Promise<DashboardResponse>;
};

export function useDashboardData(symbol: string | null) {
  const queryClient = useQueryClient();
  const setActiveAsset = useDashboardStore((state) => state.setActiveAsset);
  const setCapabilities = useDashboardStore((state) => state.setCapabilities);
  const setDashboardData = useDashboardStore((state) => state.setDashboardData);
  const setLoading = useDashboardStore((state) => state.setLoading);
  const setError = useDashboardStore((state) => state.setError);
  const query = useQuery({
    queryKey: dashboardQueryKey(symbol || ''),
    queryFn: ({ signal }) => fetchDashboard(symbol!, signal),
    enabled: Boolean(symbol),
  });
  const { data, error, isFetching } = query;

  useEffect(() => {
    setLoading(isFetching);
    setError(error instanceof Error ? error.message : null);
    if (!data) return;
    setActiveAsset(data.state.active_asset);
    setCapabilities(data.state.capabilities);
    setDashboardData(data.data);
  }, [data, error, isFetching, setActiveAsset, setCapabilities, setDashboardData, setError, setLoading]);

  const refetch = useCallback(async (nextSymbol: string) => {
    const normalized = nextSymbol.trim();
    if (!normalized) return;
    setLoading(true);
    setError(null);
    try {
      const data = await queryClient.fetchQuery({
        queryKey: dashboardQueryKey(normalized),
        queryFn: ({ signal }) => fetchDashboard(normalized, signal),
        staleTime: 0,
      });
      setActiveAsset(data.state.active_asset);
      setCapabilities(data.state.capabilities);
      setDashboardData(data.data);
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Failed to load dashboard');
    } finally {
      setLoading(false);
    }
  }, [queryClient, setActiveAsset, setCapabilities, setDashboardData, setError, setLoading]);

  return { refetch };
}
