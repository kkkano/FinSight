import { describe, expect, it } from 'vitest';
import type { RawSSEEvent } from '../../types';
import { eventColor, eventStats, filterEvents, formatTs, projectEvents } from './eventModel';
import { serializeEvents } from './AgentLogExport';

function receipt(type: string, payload: Record<string, unknown> = {}, fields: Record<string, unknown> = {}): RawSSEEvent {
  const data = { schema_version: '2', type, event_id: type, run_id: 'run-1', agent_id: 'worker-17',
    stream_epoch: 'epoch-1', seq: 1, timestamp: '2026-11-01T08:00:00Z', payload, ...fields };
  return { id: String(data.event_id), eventType: 'any', timestamp: data.timestamp, size: 100,
    parsedData: data, rawData: JSON.stringify(data) };
}

describe('schema v2 developer event projection', () => {
  it('uses runtime identities and declared display fields instead of legacy aliases or body keywords', () => {
    const [event] = projectEvents([receipt('tool_start', { display: { title: '读取行情', target: 'AAPL', result: '原文包含error一词' } },
      { runtime_type: 'tool.started', agent_id: 'unlisted-worker', parent_agent_id: 'root' })]);
    expect(event.frame.type).toBe('tool.started');
    expect(event.agentLabel).toBe('unlisted-worker');
    expect(event.frame).toMatchObject({ agent_id: 'unlisted-worker', parent_agent_id: 'root', seq: 1, run_id: 'run-1' });
    expect(event.summary).toBe('读取行情 · AAPL · 原文包含error一词');
    expect(eventColor(event)).toBe('text-t-text2');
  });

  it('excludes old plan records and provider reasoning from the developer projection', () => {
    const legacy = receipt('thinking', { summary: '旧计划' }, { schema_version: '1' });
    expect(projectEvents([legacy, receipt('reasoning.delta', { delta: 'private-reasoning' }),
      receipt('content.delta', { delta: '正文属于消息块' })])).toEqual([]);
  });

  it('deduplicates replayed event identities while preserving another attempt', () => {
    const first = receipt('tool.started');
    const repeated = { ...first, id: 'another-receipt' };
    expect(projectEvents([first, repeated, receipt('tool.started', {}, { stream_epoch: 'epoch-2' })])).toHaveLength(2);
  });

  it('keeps independent worker instances and run identities through filtering', () => {
    const events = projectEvents([
      receipt('agent.started', { role: 'news_agent', task: '核实AAPL' }),
      receipt('agent.started', { role: 'news_agent', task: '核实MSFT' }, { run_id: 'run-2' }),
      receipt('tool.result', { summary: '已取得披露' }),
    ]);
    expect(filterEvents(events, 'msft', new Set(), null)).toEqual([events[1]]);
    expect(filterEvents(events, '', new Set(['agent.started']), new Set([events[0].agentKey]))).toEqual([events[0]]);
  });

  it('retains multi-agent/type filters and distinguishes all agents from an explicit empty selection', () => {
    const events = projectEvents([receipt('agent.started'), receipt('tool.result'),
      receipt('agent.started', {}, { agent_id: 'worker-2', event_id: 'worker-2-start' })]);
    expect(filterEvents(events, '', new Set(['agent.started', 'tool.result']), new Set(events.map((event) => event.agentKey)))).toEqual(events);
    expect(filterEvents(events, '', new Set(), new Set())).toEqual([]);
    expect(filterEvents(events, '', new Set(), null)).toEqual(events);
  });

  it('counts concurrent lifecycles from recorded starts and terminals without a progress estimate', () => {
    const events = projectEvents([
      receipt('agent.started'),
      receipt('agent.started', {}, { agent_id: 'worker-18', event_id: 'second-start' }),
      receipt('agent.finished', { status: 'completed' }),
    ]);
    expect(eventStats(events, 1)).toMatchObject({ total: 3, filtered: 1, runningAgents: 1, totalBytes: 300 });
    const failed = projectEvents([receipt('agent.failed', { status: 'failed' }, { agent_id: 'worker-18' })]);
    expect(eventStats([...events, ...failed], 4).runningAgents).toBe(0);
    expect(eventColor(failed[0])).toBe('text-t-error');
    expect(eventColor(projectEvents([receipt('agent.finished', { status: 'cancelled' })])[0])).toBe('text-t-warning');
  });

  it('uses local time consistently for timestamps with different timezone representations', () => {
    expect(formatTs('2026-11-01T08:00:00Z')).toBe(formatTs('2026-11-01T16:00:00+08:00'));
  });

  it('exports v2 headers and payload while redacting secrets without mutating the receipt', () => {
    const original = receipt('tool.failed', { api_key: 'secret-fixture-key', message: 'authorization: bearer private-fixture-token', status: 'failed' });
    const events = projectEvents([original]);
    const json = serializeEvents(events);
    expect(JSON.parse(json)[0]).toMatchObject({ schema_version: '2', type: 'tool.failed', run_id: 'run-1', agent_id: 'worker-17', seq: 1 });
    expect(json).not.toContain('secret-fixture-key');
    expect(json).not.toContain('private-fixture-token');
    expect(original.parsedData.payload.api_key).toBe('secret-fixture-key');
  });
});
