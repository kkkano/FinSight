import { useCallback, useEffect, useState } from 'react';
import { apiClient, type PortfolioSummaryResponse } from '../api/client';

interface UsePortfolioSummaryResult {
  data: PortfolioSummaryResponse | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

/** 单条订阅回调：缓存数据变化时广播给所有实例 */
type Listener = (entry: CacheEntry) => void;

/** 每个 sessionId 一份模块级缓存（多个 hook 实例共享，避免 N 份轮询） */
interface CacheEntry {
  data: PortfolioSummaryResponse | null;
  loading: boolean;
  error: string | null;
  listeners: Set<Listener>;
  timer: number | null;
  /** 进行中的请求——用于去重（同一时刻只发一个网络请求） */
  inflight: Promise<void> | null;
}

const POLL_INTERVAL_MS = 60_000;

// sessionId -> 缓存条目。模块级单例，跨组件共享。
const cacheStore = new Map<string, CacheEntry>();

/** 取得（或惰性创建）某个 sessionId 的缓存条目 */
function getOrCreateEntry(sessionId: string): CacheEntry {
  let entry = cacheStore.get(sessionId);
  if (!entry) {
    entry = {
      data: null,
      loading: false,
      error: null,
      listeners: new Set(),
      timer: null,
      inflight: null,
    };
    cacheStore.set(sessionId, entry);
  }
  return entry;
}

/** 向某条目的所有监听者广播最新快照 */
function notify(entry: CacheEntry): void {
  for (const listener of entry.listeners) {
    listener(entry);
  }
}

/**
 * 触发一次拉取（带去重）。
 * 已有 inflight 请求时复用同一个 promise，不重复打后端。
 */
function fetchSummary(sessionId: string): Promise<void> {
  const entry = getOrCreateEntry(sessionId);
  if (entry.inflight) {
    return entry.inflight;
  }

  entry.loading = true;
  entry.error = null;
  notify(entry);

  const promise = apiClient
    .getPortfolioSummary(sessionId)
    .then((payload) => {
      entry.data = payload;
      entry.error = null;
    })
    .catch((err: unknown) => {
      entry.data = null;
      entry.error = err instanceof Error ? err.message : 'Failed to load portfolio summary';
    })
    .finally(() => {
      entry.loading = false;
      entry.inflight = null;
      notify(entry);
    });

  entry.inflight = promise;
  return promise;
}

/** 引用计数 +1：第一个订阅者启动 60s 轮询定时器 */
function subscribe(sessionId: string, listener: Listener): void {
  const entry = getOrCreateEntry(sessionId);
  entry.listeners.add(listener);
  if (entry.timer === null) {
    entry.timer = window.setInterval(() => {
      void fetchSummary(sessionId);
    }, POLL_INTERVAL_MS);
  }
}

/** 引用计数 -1：最后一个订阅者 unmount 时清掉定时器并释放缓存 */
function unsubscribe(sessionId: string, listener: Listener): void {
  const entry = cacheStore.get(sessionId);
  if (!entry) return;
  entry.listeners.delete(listener);
  if (entry.listeners.size === 0) {
    if (entry.timer !== null) {
      window.clearInterval(entry.timer);
      entry.timer = null;
    }
    // 无人订阅时移除缓存，避免内存随会话切换无限增长
    cacheStore.delete(sessionId);
  }
}

export function usePortfolioSummary(sessionId: string | null | undefined): UsePortfolioSummaryResult {
  const [data, setData] = useState<PortfolioSummaryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!sessionId) {
      setData(null);
      setLoading(false);
      setError(null);
      return;
    }
    await fetchSummary(sessionId);
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId) {
      setData(null);
      setLoading(false);
      setError(null);
      return;
    }

    // 订阅缓存广播：任何实例 refresh 成功后，所有实例同步更新
    const listener: Listener = (entry) => {
      setData(entry.data);
      setLoading(entry.loading);
      setError(entry.error);
    };
    subscribe(sessionId, listener);

    // 立即同步当前缓存快照（可能已有其他实例拉取过）
    const current = cacheStore.get(sessionId);
    if (current) {
      setData(current.data);
      setLoading(current.loading);
      setError(current.error);
      // 首次挂载且无数据、无进行中请求时主动拉一次
      if (current.data === null && current.inflight === null) {
        void fetchSummary(sessionId);
      }
    }

    return () => {
      unsubscribe(sessionId, listener);
    };
  }, [sessionId]);

  return { data, loading, error, refresh };
}

/** 从 summary 数据构建 {ticker: shares} 快查表（旧组件迁移用） */
export function buildPositionsMap(data: PortfolioSummaryResponse | null): Record<string, number> {
  if (!data || !Array.isArray(data.positions)) return {};
  return data.positions.reduce<Record<string, number>>((acc, pos) => {
    const ticker = String(pos?.ticker || '').trim().toUpperCase();
    const shares = Number(pos?.shares);
    if (ticker && Number.isFinite(shares) && shares > 0) {
      acc[ticker] = shares;
    }
    return acc;
  }, {});
}
