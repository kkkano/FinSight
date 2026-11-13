import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import type { RawSSEEvent } from '../../types';
import { AgentLogPanel } from './AgentLogPanel';
import { EventDetail } from './AgentEventRow';
import { projectEvents } from './eventModel';

const state = vi.hoisted(() => ({ rawEvents: [] as RawSSEEvent[], isConsoleOpen: true,
  traceRawShowRawJson: true, clearRawEvents: vi.fn(), setConsoleOpen: vi.fn(), setTraceRawShowRawJson: vi.fn() }));
vi.mock('../../store/useStore', () => ({ useStore: () => state }));

beforeEach(() => { state.rawEvents = []; state.isConsoleOpen = true; });

const event = (payload: Record<string, unknown>): RawSSEEvent => ({ id: 'receipt', eventType: 'any',
  timestamp: '2026-11-01T08:00:00Z', size: 42, rawData: JSON.stringify(payload),
  parsedData: { schema_version: '2', type: 'tool.result', run_id: 'run-1', agent_id: 'worker-1', seq: 2, payload } });

describe('developer AgentLogPanel', () => {
  it('keeps the console and displays declared v2 activity with accessible filters', () => {
    state.rawEvents = [event({ agent_label: '新闻分析师', display: { title: '读取公告', target: 'AAPL', result: '原文已取得' } })];
    const html = renderToStaticMarkup(<AgentLogPanel />);
    expect(html).toContain('Console');
    expect(html).toContain('schema v2');
    expect(html).toContain('读取公告 · AAPL · 原文已取得');
    expect(html).toContain('新闻分析师');
    expect(html).toContain('aria-label="事件类型"');
    expect(html).toContain('aria-label="Agent"');
    expect(html).toContain('1/1');
  });

  it('keeps the collapsed entry without rendering an obsolete pipeline', () => {
    state.isConsoleOpen = false;
    const html = renderToStaticMarkup(<AgentLogPanel />);
    expect(html).toContain('Console');
    expect(html).not.toContain('规划');
    expect(html).not.toContain('aria-label="事件类型"');
  });

  it('renders event JSON as escaped text and preserves copy/export redaction', () => {
    const [value] = projectEvents([event({ summary: '<script>window.attack()</script>', api_key: 'secret-fixture-key' })]);
    const html = renderToStaticMarkup(<EventDetail event={value} onClose={() => undefined} />);
    expect(html).toContain('&lt;script&gt;');
    expect(html).not.toContain('<script>');
    expect(html).not.toContain('secret-fixture-key');
    expect(html).toContain('复制事件JSON');
  });
});
