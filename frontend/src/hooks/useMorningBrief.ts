import { useCallback, useEffect, useRef, useState } from 'react';

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

const loadPersistedBrief = (sessionId: string): PersistedMorningBrief | null => {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(buildStorageKey(sessionId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<PersistedMorningBrief>;
    if (!parsed || typeof parsed !== 'object' || !parsed.brief) return null;
    return {
      brief: parsed.brief as MorningBriefData,
      generatedAt: typeof parsed.generatedAt === 'string' ? parsed.generatedAt : null,
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
  const [brief, setBrief] = useState<MorningBriefData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [generatedAt, setGeneratedAt] = useState<string | null>(null);

  // 防止并发请求
  const inflightRef = useRef(false);

  // session 切换时恢复缓存晨报
  useEffect(() => {
    const sid = String(sessionId || '').trim();
    if (!sid) {
      setBrief(null);
      setGeneratedAt(null);
      setError(null);
      return;
    }
    const cached = loadPersistedBrief(sid);
    if (!cached) {
      setBrief(null);
      setGeneratedAt(null);
      setError(null);
      return;
    }
    setBrief(cached.brief);
    setGeneratedAt(cached.generatedAt || cached.brief.generated_at || null);
    setError(null);
  }, [sessionId]);

  const generate = useCallback(async (tickers?: string[]) => {
    if (!sessionId) {
      setError('会话未初始化，请刷新页面后重试');
      return;
    }

    if (inflightRef.current) {
      return;
    }

    inflightRef.current = true;
    setLoading(true);
    setError(null);

    try {
      const response = await apiClient.generateMorningBrief({
        session_id: sessionId,
        tickers: tickers ?? [],
      });

      if (response.success && response.brief) {
        const nextGeneratedAt = response.brief.generated_at ?? new Date().toISOString();
        setBrief(response.brief);
        setGeneratedAt(nextGeneratedAt);
        savePersistedBrief(sessionId, response.brief, nextGeneratedAt);
      } else {
        setError('晨报生成失败，请稍后重试');
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : '网络异常，请检查连接后重试';
      setError(message);
    } finally {
      setLoading(false);
      inflightRef.current = false;
    }
  }, [sessionId]);

  return { brief, loading, error, generate, generatedAt };
}
