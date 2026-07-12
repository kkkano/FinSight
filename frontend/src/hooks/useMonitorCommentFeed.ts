import { useEffect, useState } from 'react';
import { buildAuthHeaders } from '../api/http';
import { buildApiUrl } from '../config/runtime';

export type MonitorComment = {
  id: string;
  session_id: string;
  symbol: string;
  ts: string;
  level: 'info' | 'warn' | 'alert' | 'error';
  text: string;
  trigger: { kind: string; detail: string; observed_at: string };
  source: 'agent' | 'system';
  escalated: boolean;
  prediction_id: string | null;
  chart_url: string | null;
};

function mergeComments(previous: MonitorComment[], incoming: MonitorComment[]): MonitorComment[] {
  const byId = new Map(previous.map((item) => [item.id, item]));
  incoming.forEach((item) => byId.set(item.id, item));
  return [...byId.values()].sort((a, b) => b.ts.localeCompare(a.ts));
}

export function useMonitorCommentFeed(sessionId: string | null | undefined) {
  const [comments, setComments] = useState<MonitorComment[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!sessionId) {
      setComments([]);
      return undefined;
    }
    const controller = new AbortController();
    let retries = 0;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let lastEventId = '';

    const connect = async () => {
      try {
        const suffix = lastEventId ? `&last_event_id=${encodeURIComponent(lastEventId)}` : '';
        const response = await fetch(
          buildApiUrl(`/api/monitor/comments/stream?session_id=${encodeURIComponent(sessionId)}${suffix}`),
          { headers: await buildAuthHeaders(), signal: controller.signal },
        );
        if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`);
        retries = 0;
        setError(null);
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        while (!controller.signal.aborted) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const frames = buffer.split(/\r?\n\r?\n/);
          buffer = frames.pop() ?? '';
          for (const frame of frames) {
            const event = frame.match(/^event:\s*(.+)$/m)?.[1] ?? 'message';
            const id = frame.match(/^id:\s*(.+)$/m)?.[1];
            const data = frame.match(/^data:\s*(.*)$/m)?.[1];
            if (!data || event === 'heartbeat') continue;
            if (id) lastEventId = id;
            const parsed = JSON.parse(data) as MonitorComment | MonitorComment[];
            if (event === 'snapshot' && Array.isArray(parsed)) setComments(mergeComments([], parsed));
            if (event === 'comment' && !Array.isArray(parsed)) setComments((prev) => mergeComments(prev, [parsed]));
          }
        }
        if (!controller.signal.aborted) throw new Error('stream closed');
      } catch (reason) {
        if (controller.signal.aborted) return;
        setError(reason instanceof Error ? reason.message : '点评流不可用');
        if (retries < 3) {
          retries += 1;
          retryTimer = setTimeout(() => void connect(), retries * 1_000);
        }
      }
    };

    void connect();
    return () => {
      controller.abort();
      if (retryTimer) clearTimeout(retryTimer);
    };
  }, [sessionId]);

  return { comments, error };
}

