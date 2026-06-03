/**
 * useMonitorSettings.ts —— 通知设置数据 hook
 *
 * 负责拉取 / 更新邮件通知设置（邮箱 + 开关）。
 * SMTP 未配置时（smtp_configured=false），后端会在启用时返回 422。
 */
import { useCallback, useEffect, useState } from 'react';

import { apiClient } from '../api/client';
import type { MonitorSettingsResponse } from '../types/monitor';

interface UseMonitorSettingsResult {
  settings: MonitorSettingsResponse | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  /** 保存设置；成功返回 true，失败返回 false 并把后端错误写入 error */
  save: (notifyEmail: string | null, notifyEnabled: boolean) => Promise<boolean>;
}

/** 从 axios/fetch 错误中尽量提取后端的中文 detail 文案 */
function extractErrorMessage(err: unknown, fallback: string): string {
  // axios 错误：后端 422 的中文提示在 response.data.detail
  if (typeof err === 'object' && err !== null) {
    const maybe = err as { response?: { data?: { detail?: unknown } }; message?: string };
    const detail = maybe.response?.data?.detail;
    if (typeof detail === 'string' && detail.trim()) return detail;
    if (typeof maybe.message === 'string' && maybe.message.trim()) return maybe.message;
  }
  return fallback;
}

export function useMonitorSettings(
  sessionId: string | null | undefined,
): UseMonitorSettingsResult {
  const [settings, setSettings] = useState<MonitorSettingsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!sessionId) {
      setSettings(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await apiClient.getMonitorSettings(sessionId);
      setSettings(res);
    } catch (err) {
      setError(extractErrorMessage(err, '加载通知设置失败'));
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  const save = useCallback(
    async (notifyEmail: string | null, notifyEnabled: boolean): Promise<boolean> => {
      if (!sessionId) return false;
      setError(null);
      try {
        await apiClient.updateMonitorSettings(sessionId, notifyEmail, notifyEnabled);
        await refresh();
        return true;
      } catch (err) {
        setError(extractErrorMessage(err, '保存通知设置失败'));
        return false;
      }
    },
    [sessionId, refresh],
  );

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { settings, loading, error, refresh, save };
}
