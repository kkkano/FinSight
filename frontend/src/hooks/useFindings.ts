/**
 * useFindings.ts —— 发现流数据 hook
 *
 * 负责：拉取 findings、60 秒轮询、手动扫描、标记已读。
 * 轮询在组件卸载时清理；扫描期间禁用并发。
 */
import { useCallback, useEffect, useRef, useState } from 'react';

import { apiClient } from '../api/client';
import type { Finding, FindingStatus } from '../types/monitor';

/** 发现流轮询间隔（毫秒） */
const FINDINGS_POLL_INTERVAL_MS = 60_000;

interface UseFindingsResult {
  /** 发现列表（已按未读优先 + 时间倒序排序） */
  findings: Finding[];
  loading: boolean;
  error: string | null;
  /** 是否正在手动扫描 */
  scanning: boolean;
  /** 手动刷新 */
  refresh: () => Promise<void>;
  /** 触发立即扫描 */
  scan: () => Promise<void>;
  /** 标记某条发现为已读（乐观更新） */
  markViewed: (finding: Finding) => Promise<void>;
}

/** 未读优先 + 时间倒序排序 */
export function sortFindings(findings: Finding[]): Finding[] {
  const statusRank: Record<FindingStatus, number> = { new: 0, viewed: 1, acted: 2 };
  return [...findings].sort((a, b) => {
    const rankDiff = statusRank[a.status] - statusRank[b.status];
    if (rankDiff !== 0) return rankDiff;
    return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
  });
}

export function useFindings(sessionId: string | null | undefined): UseFindingsResult {
  const [findings, setFindings] = useState<Finding[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);

  // 防止轮询与手动刷新并发
  const inflightRef = useRef(false);

  const refresh = useCallback(async () => {
    if (!sessionId || inflightRef.current) return;

    inflightRef.current = true;
    setLoading(true);
    setError(null);
    try {
      const response = await apiClient.getFindings(sessionId);
      setFindings(sortFindings(response.findings ?? []));
    } catch (err) {
      const message = err instanceof Error ? err.message : '加载发现流失败，请稍后重试';
      setError(message);
    } finally {
      setLoading(false);
      inflightRef.current = false;
    }
  }, [sessionId]);

  const scan = useCallback(async () => {
    if (!sessionId || scanning) return;

    setScanning(true);
    setError(null);
    try {
      const response = await apiClient.triggerMonitorScan(sessionId);
      setFindings(sortFindings(response.findings ?? []));
    } catch (err) {
      const message = err instanceof Error ? err.message : '扫描失败，请稍后重试';
      setError(message);
    } finally {
      setScanning(false);
    }
  }, [sessionId, scanning]);

  const markViewed = useCallback(
    async (finding: Finding) => {
      if (!sessionId || finding.status !== 'new') return;

      // 乐观更新：先改本地状态，失败时回滚
      setFindings((prev) =>
        sortFindings(
          prev.map((item) => (item.id === finding.id ? { ...item, status: 'viewed' as const } : item)),
        ),
      );
      try {
        await apiClient.patchFindingStatus(sessionId, finding.id, 'viewed');
      } catch {
        // 回滚为新状态
        setFindings((prev) =>
          sortFindings(
            prev.map((item) => (item.id === finding.id ? { ...item, status: 'new' as const } : item)),
          ),
        );
      }
    },
    [sessionId],
  );

  // 初次加载 + 60 秒轮询
  useEffect(() => {
    if (!sessionId) {
      setFindings([]);
      return;
    }
    void refresh();
    const timer = window.setInterval(() => {
      void refresh();
    }, FINDINGS_POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [sessionId, refresh]);

  return { findings, loading, error, scanning, refresh, scan, markViewed };
}
