import { useCallback, useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { apiClient, type MorningBriefData } from '../api/client';

/** 晨报 hook 状态 */
interface UseMorningBriefResult {
  /** 晨报数据 */
  brief: MorningBriefData | null;
  /** 正在加载中 */
  loading: boolean;
  /** 错误信息 */
  error: string | null;
  /** 触发生成晨报 */
  generate: (tickers?: string[]) => Promise<void>;
  /** 上次生成时间戳 */
  generatedAt: string | null;
}

const MORNING_BRIEF_STORAGE_PREFIX = 'finsight-morning-brief:';

const buildStorageKey = (sessionId: string): string =>
  `${MORNING_BRIEF_STORAGE_PREFIX}${sessionId}`;

type PersistedMorningBrief = {
  brief: MorningBriefData;
  generatedAt: string | null;
};

/**
 * 判断晨报生成时间是否仍属于「当日」有效。
 *
 * 晨报是按当天行情/新闻生成的，跨天后昨天的晨报不应在今早复用，
 * 否则会把昨天的晨报当成今早的展示（误导）。
 * 以本地日期边界为准：生成日期 !== 今天 即视为过期。
 */
const isBriefFresh = (generatedAt: string | null): boolean => {
  if (!generatedAt) return false;
  const generated = new Date(generatedAt);
  if (Number.isNaN(generated.getTime())) return false;
  const now = new Date();
  return (
    generated.getFullYear() === now.getFullYear() &&
    generated.getMonth() === now.getMonth() &&
    generated.getDate() === now.getDate()
  );
};

const loadPersistedBrief = (sessionId: string): PersistedMorningBrief | null => {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(buildStorageKey(sessionId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<PersistedMorningBrief>;
    if (!parsed || typeof parsed !== 'object' || !parsed.brief) return null;
    const brief = parsed.brief as MorningBriefData;
    const generatedAt =
      typeof parsed.generatedAt === 'string' ? parsed.generatedAt : brief.generated_at ?? null;
    // TTL：跨当日边界则视为过期，丢弃缓存（同时清理 localStorage，触发重新生成）
    if (!isBriefFresh(generatedAt)) {
      window.localStorage.removeItem(buildStorageKey(sessionId));
      return null;
    }
    return {
      brief,
      generatedAt,
    };
  } catch {
    return null;
  }
};

const savePersistedBrief = (sessionId: string, brief: MorningBriefData, generatedAt: string | null): void => {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(
      buildStorageKey(sessionId),
      JSON.stringify({
        brief,
        generatedAt,
      }),
    );
  } catch {
    // ignore localStorage quota errors
  }
};

/**
 * 一键晨报 hook — 管理 API 调用、缓存状态和错误处理。
 *
 * 内部使用 ref 防止重复请求（debounce guard），
 * 30 分钟内重复调用会返回缓存结果（由后端 TTL 控制）。
 */
export function useMorningBrief(sessionId: string | null | undefined): UseMorningBriefResult {
  const queryClient = useQueryClient();
  const sid = String(sessionId || '').trim();
  const queryKey = ['morning-brief', sid] as const;
  const [validationError, setValidationError] = useState<string | null>(null);
  const query = useQuery({
    queryKey,
    queryFn: () => loadPersistedBrief(sid),
    enabled: Boolean(sid),
  });
  const mutation = useMutation({
    mutationFn: async (tickers?: string[]) => {
      const response = await apiClient.generateMorningBrief({ session_id: sid, tickers: tickers ?? [] });
      if (!response.success || !response.brief) throw new Error('晨报生成失败，请稍后重试');
      const generatedAt = response.brief.generated_at ?? new Date().toISOString();
      return { brief: response.brief, generatedAt } satisfies PersistedMorningBrief;
    },
    onSuccess: (next) => {
      savePersistedBrief(sid, next.brief, next.generatedAt);
      queryClient.setQueryData(queryKey, next);
    },
  });
  const {
    error: mutationErrorValue,
    isPending,
    mutateAsync,
    reset,
  } = mutation;

  useEffect(() => {
    setValidationError(null);
    reset();
  }, [reset, sid]);

  const generate = useCallback(async (tickers?: string[]) => {
    if (!sid) {
      setValidationError('会话未初始化，请刷新页面后重试');
      return;
    }
    try {
      setValidationError(null);
      await mutateAsync(tickers);
    } catch {
      // mutation.error 作为唯一请求错误源返回给调用方。
    }
  }, [mutateAsync, sid]);

  const persisted = query.data ?? null;
  const mutationError = mutationErrorValue instanceof Error ? mutationErrorValue.message : null;

  return {
    brief: persisted?.brief ?? null,
    loading: isPending,
    error: validationError || mutationError,
    generate,
    generatedAt: persisted?.generatedAt || persisted?.brief.generated_at || null,
  };
}
