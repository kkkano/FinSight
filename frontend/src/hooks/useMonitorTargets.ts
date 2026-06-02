/**
 * useMonitorTargets.ts —— 盯盘对象数据 hook
 *
 * 负责拉取 / 创建 / 更新（阈值、开关）/ 删除盯盘对象。
 */
import { useCallback, useEffect, useState } from 'react';

import { apiClient } from '../api/client';
import type {
  CreateMonitorTargetParams,
  MonitorTarget,
  PatchMonitorTargetParams,
} from '../types/monitor';

interface UseMonitorTargetsResult {
  targets: MonitorTarget[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  createTarget: (params: Omit<CreateMonitorTargetParams, 'session_id'>) => Promise<boolean>;
  patchTarget: (targetId: string, params: PatchMonitorTargetParams) => Promise<boolean>;
  deleteTarget: (targetId: string) => Promise<boolean>;
}

export function useMonitorTargets(sessionId: string | null | undefined): UseMonitorTargetsResult {
  const [targets, setTargets] = useState<MonitorTarget[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!sessionId) {
      setTargets([]);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const response = await apiClient.getMonitorTargets(sessionId);
      setTargets(response.targets ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载监控配置失败');
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  const createTarget = useCallback(
    async (params: Omit<CreateMonitorTargetParams, 'session_id'>): Promise<boolean> => {
      if (!sessionId) return false;
      try {
        await apiClient.createMonitorTarget({ ...params, session_id: sessionId });
        await refresh();
        return true;
      } catch (err) {
        setError(err instanceof Error ? err.message : '添加监控失败');
        return false;
      }
    },
    [sessionId, refresh],
  );

  const patchTarget = useCallback(
    async (targetId: string, params: PatchMonitorTargetParams): Promise<boolean> => {
      if (!sessionId) return false;
      // 乐观更新开关
      if (params.enabled !== undefined) {
        setTargets((prev) =>
          prev.map((t) => (t.id === targetId ? { ...t, enabled: params.enabled! } : t)),
        );
      }
      try {
        await apiClient.patchMonitorTarget(sessionId, targetId, params);
        await refresh();
        return true;
      } catch (err) {
        setError(err instanceof Error ? err.message : '更新监控失败');
        await refresh();
        return false;
      }
    },
    [sessionId, refresh],
  );

  const deleteTarget = useCallback(
    async (targetId: string): Promise<boolean> => {
      if (!sessionId) return false;
      try {
        await apiClient.deleteMonitorTarget(sessionId, targetId);
        await refresh();
        return true;
      } catch (err) {
        setError(err instanceof Error ? err.message : '删除监控失败');
        return false;
      }
    },
    [sessionId, refresh],
  );

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { targets, loading, error, refresh, createTarget, patchTarget, deleteTarget };
}
