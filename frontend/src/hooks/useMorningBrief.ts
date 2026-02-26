import { useCallback, useRef, useState } from 'react';

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
        setBrief(response.brief);
        setGeneratedAt(response.brief.generated_at ?? new Date().toISOString());
      } else {
        setError('晨报生成失败，请稍后重试');
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : '网络异常，请检查连接后重试';
      setError(message);
      setBrief(null);
    } finally {
      setLoading(false);
      inflightRef.current = false;
    }
  }, [sessionId]);

  return { brief, loading, error, generate, generatedAt };
}
