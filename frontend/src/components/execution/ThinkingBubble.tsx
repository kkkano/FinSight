import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Loader2 } from 'lucide-react';

import type { TimelineEvent } from '../../types/execution';
import { resolveUserMessage } from '../../utils/userMessageMapper';

/** 最大同时显示的思考气泡数量 */
const MAX_VISIBLE_BUBBLES = 5;

/** SSE 事件节流间隔（ms），防止短时间大量气泡闪烁 */
const THROTTLE_MS = 80;

type BubbleItem = {
  id: string;
  text: string;
  isDone: boolean;
  timestamp: number;
};

type ThinkingBubbleProps = {
  timeline: TimelineEvent[];
  isRunning: boolean;
  className?: string;
};

/**
 * ThinkingBubble — 用户模式下的思考气泡组件。
 *
 * 从 timeline 事件流中提取 userMessage，以气泡形式展示
 * 当前分析进度。每条气泡显示一句面向用户的中文消息。
 *
 * 性能考虑：
 * - 80ms 节流防止 SSE 高频更新导致渲染抖动
 * - 最多显示 5 个气泡（FIFO 淘汰旧消息）
 * - 使用 shallow 比较减少不必要的重渲染
 */
export function ThinkingBubble({ timeline, isRunning, className = '' }: ThinkingBubbleProps) {
  const [bubbles, setBubbles] = useState<BubbleItem[]>([]);
  const lastUpdateRef = useRef<number>(0);
  const pendingRef = useRef<TimelineEvent[]>([]);
  const processedIdsRef = useRef<Set<string>>(new Set());

  const flushPending = useCallback(() => {
    const pending = pendingRef.current;
    if (pending.length === 0) return;
    pendingRef.current = [];
    lastUpdateRef.current = Date.now();

    setBubbles((prev) => {
      const next = [...prev];

      for (const evt of pending) {
        const text = resolveUserMessage(evt.stage, evt.userMessage);
        if (!text) continue;

        const isDone = evt.stage.endsWith('_done');

        // 如果是 _done 事件，标记对应的 _start 气泡为完成
        if (isDone) {
          const startStage = evt.stage.replace(/_done$/, '_start');
          const existingIdx = next.findIndex(
            (b) => b.id.includes(startStage) && !b.isDone,
          );
          if (existingIdx >= 0) {
            next[existingIdx] = { ...next[existingIdx], isDone: true, text };
            continue;
          }
        }

        // 添加新气泡
        next.push({
          id: evt.id,
          text,
          isDone,
          timestamp: Date.now(),
        });
      }

      // 保留最多 MAX_VISIBLE_BUBBLES 个气泡
      return next.slice(-MAX_VISIBLE_BUBBLES);
    });
  }, []);

  // 从 timeline 提取带 userMessage 的事件，节流处理
  useEffect(() => {
    const now = Date.now();
    const newEvents = timeline.filter(
      (evt) => !processedIdsRef.current.has(evt.id),
    );

    if (newEvents.length === 0) return;

    pendingRef.current.push(...newEvents);
    for (const evt of newEvents) {
      processedIdsRef.current.add(evt.id);
    }

    const elapsed = now - lastUpdateRef.current;
    if (elapsed < THROTTLE_MS) {
      const timer = setTimeout(() => flushPending(), THROTTLE_MS - elapsed);
      return () => clearTimeout(timer);
    }

    flushPending();
  }, [flushPending, timeline]);

  // 当执行完成时，淡出所有气泡
  useEffect(() => {
    if (!isRunning && bubbles.length > 0) {
      const timer = setTimeout(() => setBubbles([]), 1500);
      return () => clearTimeout(timer);
    }
  }, [isRunning, bubbles.length]);

  const visibleBubbles = useMemo(
    () => bubbles.filter((b) => !b.isDone || Date.now() - b.timestamp < 2000),
    [bubbles],
  );

  if (visibleBubbles.length === 0 && !isRunning) return null;

  return (
    <div className={`space-y-1.5 ${className}`}>
      {visibleBubbles.map((bubble, idx) => {
        const isLatest = idx === visibleBubbles.length - 1;
        return (
          <div
            key={bubble.id}
            className={`
              flex items-center gap-2 px-3 py-2 rounded-xl text-xs
              transition-all duration-300 ease-out
              ${bubble.isDone
                ? 'bg-emerald-500/10 text-emerald-300 border border-emerald-500/20'
                : 'bg-blue-500/10 text-blue-200 border border-blue-500/20'
              }
              ${isLatest ? 'opacity-100' : 'opacity-60'}
            `}
          >
            {!bubble.isDone && (
              <Loader2 size={12} className="animate-spin shrink-0 text-blue-400" />
            )}
            {bubble.isDone && (
              <span className="shrink-0 text-emerald-400">✓</span>
            )}
            <span className="truncate">{bubble.text}</span>
          </div>
        );
      })}
      {isRunning && visibleBubbles.length === 0 && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-xl text-xs bg-fin-bg/40 text-fin-muted border border-fin-border/40">
          <Loader2 size={12} className="animate-spin" />
          <span>正在准备分析...</span>
        </div>
      )}
    </div>
  );
}

export default ThinkingBubble;
