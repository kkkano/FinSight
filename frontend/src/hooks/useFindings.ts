/**
 * useFindings.ts —— 发现流数据 hook
 *
 * 负责：拉取 findings、60 秒轮询、手动扫描、标记已读。
 */
import { useCallback } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { apiClient } from '../api/client';
import type { Finding, FindingStatus } from '../types/monitor';

/** 发现流轮询间隔（毫秒） */
const FINDINGS_POLL_INTERVAL_MS = 60_000;

export interface UseFindingsResult {
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
  const queryClient = useQueryClient();
  const sid = String(sessionId || '').trim();
  const queryKey = ['findings', sid] as const;
  const query = useQuery({
    queryKey,
    queryFn: async () => sortFindings((await apiClient.getFindings(sid)).findings ?? []),
    enabled: Boolean(sid),
    refetchInterval: FINDINGS_POLL_INTERVAL_MS,
  });
  const {
    data,
    error: queryErrorValue,
    isFetching,
    refetch: refetchQuery,
  } = query;

  const refresh = useCallback(async () => {
    if (!sid) return;
    await refetchQuery();
  }, [refetchQuery, sid]);

  const scanMutation = useMutation({
    mutationFn: () => apiClient.triggerMonitorScan(sid),
    onSuccess: (response) => queryClient.setQueryData(queryKey, sortFindings(response.findings ?? [])),
  });
  const {
    error: scanErrorValue,
    isPending: isScanning,
    mutateAsync: scanAsync,
  } = scanMutation;
  const scan = useCallback(async () => {
    if (!sid || isScanning) return;
    try {
      await scanAsync();
    } catch {
      // mutation.error 统一暴露给 UI。
    }
  }, [isScanning, scanAsync, sid]);

  const markMutation = useMutation({
    mutationFn: (finding: Finding) => apiClient.patchFindingStatus(sid, finding.id, 'viewed'),
    onMutate: async (finding) => {
      await queryClient.cancelQueries({ queryKey });
      const previous = queryClient.getQueryData<Finding[]>(queryKey) ?? [];
      queryClient.setQueryData(queryKey, sortFindings(
        previous.map((item) => (item.id === finding.id ? { ...item, status: 'viewed' as const } : item)),
      ));
      return previous;
    },
    onError: (_error, _finding, previous) => queryClient.setQueryData(queryKey, previous ?? []),
  });
  const { mutateAsync: markViewedAsync } = markMutation;
  const markViewed = useCallback(async (finding: Finding) => {
    if (!sid || finding.status !== 'new') return;
    try {
      await markViewedAsync(finding);
    } catch {
      // 乐观更新已由 onError 回滚。
    }
  }, [markViewedAsync, sid]);

  const queryError = queryErrorValue instanceof Error ? queryErrorValue.message : null;
  const scanError = scanErrorValue instanceof Error ? scanErrorValue.message : null;

  return {
    findings: data ?? [],
    loading: isFetching,
    error: scanError || queryError,
    scanning: isScanning,
    refresh,
    scan,
    markViewed,
  };
}
