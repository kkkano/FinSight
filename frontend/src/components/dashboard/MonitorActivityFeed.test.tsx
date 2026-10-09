import { describe, expect, it } from 'vitest';

import type { MonitorComment } from '../../hooks/useMonitorCommentFeed';
import { foldHeartbeatComments } from './MonitorActivityFeed';

const make = (
  id: string,
  kind: string,
  level: MonitorComment['level'],
  minute: number,
): MonitorComment => ({
  id,
  session_id: 's1',
  symbol: 'AAPL',
  ts: `2026-07-11T00:${String(minute).padStart(2, '0')}:00Z`,
  level,
  text: id,
  trigger: { kind, detail: id, observed_at: 'now' },
  source: 'agent',
  escalated: false,
  prediction_id: null,
  chart_url: null,
});

describe('MonitorActivityFeed heartbeat folding', () => {
  it('folds consecutive info heartbeats but never folds alerts', () => {
    const items = foldHeartbeatComments([
      make('h2', 'heartbeat', 'info', 10),
      make('h1', 'heartbeat', 'info', 5),
      make('alert', 'prediction_level_break', 'alert', 4),
      make('h0', 'heartbeat', 'info', 0),
    ]);
    expect(items).toHaveLength(3);
    expect(items[0]).toMatchObject({ kind: 'heartbeat', count: 2 });
    expect(items[1]).toMatchObject({ kind: 'comment', comment: { id: 'alert' } });
    expect(items[2]).toMatchObject({ kind: 'heartbeat', count: 1 });
  });

  it('preserves failed heartbeat details separately from successful checks', () => {
    const items = foldHeartbeatComments([
      make('legacy-error', 'heartbeat', 'error', 10),
      make('legacy-info', 'heartbeat', 'info', 5),
    ]);

    expect(items).toHaveLength(2);
    expect(items[0]).toMatchObject({ kind: 'errors', comments: [{ id: 'legacy-error', level: 'error' }] });
    expect(items[1]).toMatchObject({ kind: 'heartbeat', count: 1 });
  });

  it('aggregates repeated failures without losing their original timestamps or reasons', () => {
    const older = { ...make('old', 'heartbeat', 'error', 5), ts: '2026-09-15T10:00:00Z', text: 'APIConnectionError' };
    const newer = { ...make('new', 'heartbeat', 'error', 10), ts: '2026-10-02T15:00:00Z', text: 'NotFoundError' };
    expect(foldHeartbeatComments([newer, older])[0]).toMatchObject({ kind: 'errors', comments: [newer, older] });
  });
});
