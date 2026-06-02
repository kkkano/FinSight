/**
 * P1-8: 429 限流全局 toast 提示
 *
 * 监听 client.ts 派发的限流事件（axios 拦截器 / 流式 fetch 均会触发），
 * 弹出 warning toast，带 Retry-After 倒计时秒数提示。
 */

import { useEffect } from 'react';

import { RATE_LIMIT_EVENT, rateLimitEvents } from '../../api/client';
import { useToast } from '../ui/Toast';

/** toast 最长显示时长（毫秒），避免 Retry-After 过大时通知长期占屏 */
const MAX_TOAST_DURATION_MS = 15_000;

/** 默认显示时长（毫秒，无 Retry-After 信息时） */
const DEFAULT_TOAST_DURATION_MS = 8_000;

export function RateLimitToastListener() {
  const { toast } = useToast();

  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent).detail ?? {};
      const seconds: number | null = detail.retryAfterSeconds ?? null;

      toast({
        type: 'warning',
        title: '请求过于频繁',
        message: seconds
          ? `服务器限流中，请约 ${seconds} 秒后重试`
          : '服务器限流中，请稍后重试',
        duration: seconds
          ? Math.min(seconds * 1000, MAX_TOAST_DURATION_MS)
          : DEFAULT_TOAST_DURATION_MS,
      });
    };

    rateLimitEvents.addEventListener(RATE_LIMIT_EVENT, handler);
    return () => rateLimitEvents.removeEventListener(RATE_LIMIT_EVENT, handler);
  }, [toast]);

  return null;
}
