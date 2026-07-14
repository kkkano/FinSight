import { describe, expect, it } from 'vitest';

import type { DailyTask } from '../../api/client';
import type { Finding } from '../../types/monitor';
import type { TaskRunState } from './taskStateMachine';
import { selectTaskRunItems, selectTodayQueue } from './todayQueue';

const task = (id: string, priority: number): DailyTask => ({
  id,
  title: id,
  category: 'research',
  priority,
  action_url: '',
  icon: 'FileSearch',
  status: 'pending',
  execution_params: null,
});

const run = (status: TaskRunState['status'], updatedAt: string): TaskRunState => ({
  status,
  updatedAt,
  step: null,
  progress: 0,
  reportId: null,
  error: null,
  interruptData: null,
  expiresAt: null,
});

const finding = (id: string, createdAt: string, status: Finding['status'] = 'new'): Finding => ({
  id,
  session_id: 's1',
  created_at: createdAt,
  target: 'AAPL',
  trigger_type: 'price_move',
  trigger_detail: {},
  title: id,
  summary: id,
  agent_analysis: null,
  actions: [],
  status,
});

describe('todayQueue', () => {
  it('keeps every task row while local interrupted state overrides backend pending', () => {
    const rows = selectTaskRunItems(
      [task('a', 2), task('b', 1)],
      { a: run('interrupted', '2026-07-14T10:00:00Z') },
    );
    expect(rows.map((item) => [item.identity, item.status])).toEqual([
      ['task:a', 'interrupted'],
      ['task:b', 'pending'],
    ]);
  });

  it('sorts new findings, interrupted tasks and pending tasks with stable identities before limiting', () => {
    const rows = selectTaskRunItems(
      [task('pending-low', 3), task('interrupted', 1), task('pending-high', 1)],
      { interrupted: run('interrupted', '2026-07-14T09:00:00Z') },
    );
    const queue = selectTodayQueue([
      finding('old', '2026-07-14T08:00:00Z'),
      finding('viewed', '2026-07-14T11:00:00Z', 'viewed'),
      finding('new', '2026-07-14T10:00:00Z'),
    ], rows, 4);

    expect(queue.map((item) => item.identity)).toEqual([
      'finding:new',
      'finding:old',
      'task:interrupted',
      'task:pending-high',
    ]);
  });
});
