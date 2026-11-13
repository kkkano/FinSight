import type { RawSSEEvent } from '../../types';
import type { RuntimeEvent } from '../../types/runtime';
import { normalizeRuntimeEvent } from '../../store/researchStream';

export interface ConsoleEvent {
  id: string;
  frame: RuntimeEvent;
  agentKey: string;
  agentLabel: string;
  summary: string;
  timestamp: string;
  size: number;
}

export interface EventStats {
  total: number;
  filtered: number;
  totalBytes: number;
  typeCounts: Record<string, number>;
  runningAgents: number;
}

const text = (value: unknown): string => typeof value === 'string' ? value : '';

export function projectEvents(rawEvents: readonly RawSSEEvent[]): ConsoleEvent[] {
  const seen = new Set<string>();
  return rawEvents.flatMap((raw) => {
    if (!raw.parsedData || typeof raw.parsedData !== 'object' || Array.isArray(raw.parsedData)) return [];
    const frame = normalizeRuntimeEvent(raw.parsedData);
    // 正文和供应商原始推理继续由消息块管理，不复制进开发日志。
    if (!frame || frame.type.startsWith('content.') || frame.type.startsWith('reasoning.')) return [];
    const identity = `${frame.run_id ?? ''}:${frame.stream_epoch ?? frame.attempt_id ?? ''}:${frame.event_id ?? raw.id}`;
    if (seen.has(identity)) return [];
    seen.add(identity);
    const payload = frame.payload;
    const display = payload.display && typeof payload.display === 'object'
      ? payload.display as Record<string, unknown> : {};
    const summary = [text(display.title), text(display.target), text(display.result)].filter(Boolean).join(' · ')
      || text(payload.summary) || text(payload.task) || text(payload.message) || text(payload.name) || frame.type;
    return [{ id: identity, frame, summary, timestamp: frame.timestamp || raw.timestamp, size: raw.size,
      agentKey: `${frame.run_id ?? ''}:${frame.agent_id ?? 'root'}`,
      agentLabel: text(payload.agent_label) || text(payload.role) || frame.agent_id || 'root' }];
  });
}

export function filterEvents(events: readonly ConsoleEvent[], search: string, types: ReadonlySet<string>, agents: ReadonlySet<string> | null): ConsoleEvent[] {
  const query = search.trim().toLocaleLowerCase();
  return events.filter((event) => (!types.size || types.has(event.frame.type)) && (agents === null || agents.has(event.agentKey))
    && (!query || `${event.summary} ${JSON.stringify(event.frame)}`.toLocaleLowerCase().includes(query)));
}

export function eventStats(events: readonly ConsoleEvent[], filtered: number): EventStats {
  const agents = new Set<string>();
  const typeCounts: Record<string, number> = {};
  let totalBytes = 0;
  for (const event of events) {
    typeCounts[event.frame.type] = (typeCounts[event.frame.type] || 0) + 1;
    totalBytes += event.size;
    if (event.frame.type === 'agent.started' || event.frame.type === 'run.accepted') agents.add(event.agentKey);
    if (event.frame.type === 'agent.finished' || event.frame.type === 'agent.failed') agents.delete(event.agentKey);
    if (['run.completed', 'run.failed', 'run.cancelled'].includes(event.frame.type)) {
      for (const key of agents) if (key.startsWith(`${event.frame.run_id ?? ''}:`)) agents.delete(key);
    }
  }
  return { total: events.length, filtered, totalBytes, typeCounts, runningAgents: agents.size };
}

export function eventColor(event: ConsoleEvent): string {
  const status = event.frame.payload.status;
  if (status === 'error' || status === 'failed') return 'text-t-error';
  if (status === 'partial' || status === 'cancelled' || status === 'unavailable') return 'text-t-warning';
  if (event.frame.type.endsWith('.failed')) return 'text-t-error';
  if (event.frame.type.endsWith('.finished') || event.frame.type.endsWith('.completed')) return 'text-t-success';
  return 'text-t-text2';
}

export function formatTs(timestamp: string): string {
  const date = new Date(timestamp);
  return Number.isNaN(date.getTime()) ? timestamp : date.toLocaleTimeString('zh-CN', {
    hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit',
  });
}

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
}
