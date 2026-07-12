import { describe, expect, it } from 'vitest';
import { foldHeartbeatComments } from './MonitorCommentFeed';
import type { MonitorComment } from '../../hooks/useMonitorCommentFeed';

const make = (id: string, kind: string, level: MonitorComment['level'], minute: number): MonitorComment => ({
  id, session_id: 's1', symbol: 'AAPL', ts: `2026-07-11T00:${String(minute).padStart(2, '0')}:00Z`,
  level, text: id, trigger: { kind, detail: id, observed_at: 'now' }, source: 'agent',
  escalated: false, prediction_id: null, chart_url: null,
});

describe('MonitorCommentFeed heartbeat folding', () => {
  it('folds consecutive info heartbeat but never folds alerts', () => {
    const items = foldHeartbeatComments([
      make('h2', 'heartbeat', 'info', 10), make('h1', 'heartbeat', 'info', 5),
      make('alert', 'level_break', 'alert', 4), make('h0', 'heartbeat', 'info', 0),
    ]);
    expect(items).toHaveLength(3);
    expect(items[0]).toMatchObject({ kind: 'heartbeat', count: 2 });
    expect(items[1]).toMatchObject({ kind: 'comment', comment: { id: 'alert' } });
    expect(items[2]).toMatchObject({ kind: 'heartbeat', count: 1 });
  });
});

