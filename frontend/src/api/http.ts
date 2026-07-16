import axios from 'axios';
import { API_BASE_URL } from '../config/runtime';
import { getSupabaseClient } from './supabaseClient';

export const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json; charset=utf-8',
  },
  timeout: 30_000, // 普通 REST 请求 30s；长任务（聊天/报告/执行）走 SSE 通道不受此限，个别长耗时 POST 在调用处显式覆写
});

/**
 * 与 axios 拦截器同源的鉴权头构造，供绕过 axios 的流式 fetch 复用（FE-05）。
 */
export async function buildAuthHeaders(): Promise<Record<string, string>> {
  const client = getSupabaseClient();
  let accessToken: string | null = null;

  if (client) {
    try {
      const { data } = await client.auth.getSession();
      accessToken = data.session?.access_token || null;
    } catch {
      // Session probing is best-effort; unauthenticated requests continue without a token.
    }
  }

  return accessToken ? { Authorization: `Bearer ${accessToken}` } : {};
}

api.interceptors.request.use(async (config) => {
  const client = getSupabaseClient();
  let accessToken: string | null = null;

  if (client) {
    try {
      const { data } = await client.auth.getSession();
      accessToken = data.session?.access_token || null;
    } catch {
      // Session probing is best-effort; unauthenticated requests continue without a token.
    }
  }

  if (!accessToken) return config;

  const headers: any = config.headers ?? {};
  const hasAuthorization = typeof headers.get === 'function'
    ? Boolean(headers.get('Authorization'))
    : Boolean(headers.Authorization);

  if (!hasAuthorization) {
    if (typeof headers.set === 'function') {
      headers.set('Authorization', `Bearer ${accessToken}`);
    } else {
      headers.Authorization = `Bearer ${accessToken}`;
    }
  }

  config.headers = headers;
  return config;
});

// ---------------------------------------------------------------------------
// P1-8: 429 限流全局事件 — UI 层（RateLimitToastListener）监听后弹 toast
// ---------------------------------------------------------------------------

/** 429 限流事件名（CustomEvent，detail: { retryAfterSeconds: number | null }） */
export const RATE_LIMIT_EVENT = 'finsight:rate-limited';

/**
 * 限流事件总线。
 * 用独立 EventTarget 而非 window：拦截器/fetch 不在 React 内无法用 useToast，
 * 且独立总线在测试/SSR 环境下也能工作。
 */
export const rateLimitEvents = new EventTarget();

/** 解析 Retry-After 响应头（秒数格式），无效时返回 null */
export function parseRetryAfter(value: string | null | undefined): number | null {
  if (!value) return null;
  const seconds = Number(value);
  return Number.isFinite(seconds) && seconds > 0 ? Math.ceil(seconds) : null;
}

/** 派发全局限流事件，UI 层（RateLimitToastListener）监听后弹 toast */
export function emitRateLimitEvent(retryAfterSeconds: number | null): void {
  try {
    rateLimitEvents.dispatchEvent(
      new CustomEvent(RATE_LIMIT_EVENT, { detail: { retryAfterSeconds } }),
    );
  } catch {
    // CustomEvent 不可用的环境（极老运行时）忽略，不阻断错误处理主流程
  }
}

// 响应拦截器：处理后端返回的非 200 错误
api.interceptors.response.use(
  (response) => response,
  (error) => {
    // P1-8: 429 限流 → 派发全局事件，UI 弹 toast 提示
    if (error.response?.status === 429) {
      emitRateLimitEvent(parseRetryAfter(error.response.headers?.['retry-after']));
    }
    console.error('API Error:', error.response || error.message);
    return Promise.reject(error);
  }
);

/**
 * 检查流式 fetch 响应，429 时派发限流事件并抛出友好错误。
 * 其他非 2xx 状态抛出通用 HTTP 错误。
 */
export function ensureStreamResponseOk(response: Response): void {
  if (response.ok) return;
  if (response.status === 429) {
    emitRateLimitEvent(parseRetryAfter(response.headers.get('retry-after')));
    throw new Error('请求过于频繁，服务器限流中，请稍后再试');
  }
  throw new Error(`HTTP error! status: ${response.status}`);
}

// ---------------------------------------------------------------------------
