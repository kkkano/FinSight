import type { DailyTask } from '../../api/client';
import type { Finding } from '../../types/monitor';
import type { TaskRunState, TaskRunStatus } from './taskStateMachine';
import { toRunStateFromTask } from './taskStateMachine';

export interface TaskRunItem {
  identity: `task:${string}`;
  task: DailyTask;
  run: TaskRunState;
  status: TaskRunStatus;
  originalIndex: number;
}

export type TodayQueueItem =
  | {
      kind: 'finding';
      identity: `finding:${string}`;
      finding: Finding;
      originalIndex: number;
    }
  | {
      kind: 'task';
      identity: `task:${string}`;
      taskItem: TaskRunItem;
      originalIndex: number;
    };

function dateEpoch(value: string | null | undefined): number {
  const epoch = Date.parse(String(value ?? ''));
  return Number.isNaN(epoch) ? 0 : epoch;
}

export function selectTaskRunItems(
  tasks: DailyTask[],
  runStates: Record<string, TaskRunState>,
): TaskRunItem[] {
  return tasks.map((task, originalIndex) => {
    const run = runStates[task.id] ?? toRunStateFromTask(task);
    return {
      identity: `task:${task.id}`,
      task,
      run,
      status: run.status,
      originalIndex,
    };
  });
}

export function selectTodayQueue(
  findings: Finding[],
  taskRunItems: TaskRunItem[],
  limit = 3,
): TodayQueueItem[] {
  const candidates: Array<TodayQueueItem & { kindRank: number; sourceRank: number }> = [];

  findings.forEach((finding, originalIndex) => {
    if (finding.status !== 'new') return;
    candidates.push({
      kind: 'finding',
      identity: `finding:${finding.id}`,
      finding,
      originalIndex,
      kindRank: 0,
      sourceRank: -dateEpoch(finding.created_at),
    });
  });

  taskRunItems.forEach((taskItem) => {
    if (taskItem.status !== 'pending' && taskItem.status !== 'interrupted') return;
    candidates.push({
      kind: 'task',
      identity: taskItem.identity,
      taskItem,
      originalIndex: taskItem.originalIndex,
      kindRank: taskItem.status === 'interrupted' ? 1 : 2,
      sourceRank: taskItem.status === 'interrupted'
        ? -dateEpoch(taskItem.run.updatedAt)
        : taskItem.task.priority,
    });
  });

  const byIdentity = new Map<string, typeof candidates[number]>();
  for (const candidate of candidates) {
    const current = byIdentity.get(candidate.identity);
    if (!current || candidate.kindRank < current.kindRank) {
      byIdentity.set(candidate.identity, candidate);
    }
  }

  return [...byIdentity.values()]
    .sort((left, right) => (
      left.kindRank - right.kindRank
      || left.sourceRank - right.sourceRank
      || left.originalIndex - right.originalIndex
    ))
    .slice(0, Math.max(0, limit))
    .map(({ kindRank: _kindRank, sourceRank: _sourceRank, ...item }) => item);
}
