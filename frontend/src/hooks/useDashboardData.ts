/**
 * Dashboard 数据加载 Hook
 *
 * 封装 Dashboard API 调用、abort 控制、loading/error 状态管理。
 * 当 symbol 变化时自动重新请求，快速切换时 abort 前一个请求。
 */
import { useEffect, useRef, useCallback } from 'react';
import { useDashboardStore } from '../store/dashboardStore';
import type { DashboardResponse } from '../types/dashboard';
import { buildApiUrl } from '../config/runtime';

export function useDashboardData(symbol: string | null) {
  const {
    setActiveAsset,
    setCapabilities,
    setDashboardData,
    setLoading,
    setError,
  } = useDashboardStore();

  const abortRef = useRef<AbortController | null>(null);

  const fetchDashboard = useCallback(
    async (sym: string) => {
      // Abort 上一次请求
      if (abortRef.current) {
        abortRef.current.abort();
      }
      const controller = new AbortController();
      abortRef.current = controller;

      setLoading(true);
      setError(null);

      try {
        const response = await fetch(buildApiUrl(`/api/dashboard?symbol=${encodeURIComponent(sym)}`), {
          signal: controller.signal,
        });

        if (!response.ok) {
          const err = await response
            .json()
            .catch(() => ({ message: 'Unknown error' }));
          throw new Error(
            err?.detail?.message || err?.message || `HTTP ${response.status}`
          );
        }

        const json: DashboardResponse = await response.json();

        // 只有请求未被 abort 时才更新状态
        if (!controller.signal.aborted) {
          setActiveAsset(json.state.active_asset);
          setCapabilities(json.state.capabilities);
          setDashboardData(json.data);
        }
      } catch (err: unknown) {
        if (err instanceof Error && err.name !== 'AbortError') {
          setError(err.message || 'Failed to load dashboard');
        }
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      }
    },
    [
      setActiveAsset,
      setCapabilities,
      setDashboardData,
      setLoading,
      setError,
    ]
  );

  // symbol 变化时自动请求
  useEffect(() => {
    if (symbol) {
      fetchDashboard(symbol);
    }
    return () => {
      abortRef.current?.abort();
    };
  }, [symbol, fetchDashboard]);

  return { refetch: fetchDashboard };
}
