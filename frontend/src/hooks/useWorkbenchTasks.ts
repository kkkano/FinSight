import { useEffect, useMemo, useRef, useState } from 'react';

import { apiClient, type DailyTask } from '../api/client';
import { useDashboardStore } from '../store/dashboardStore';
import { useToast } from '../components/ui';
import {
  selectTaskRunItems,
  type TaskRunItem,
} from '../components/workbench/todayQueue';
import {
  toRunStateFromTask,
  withExpiration,
  type TaskHistoryItem,
  type TaskRunState,
} from '../components/workbench/taskStateMachine';
import { useTaskExecution } from './useTaskExecution';
import { useTaskPersistence } from './useTaskPersistence';

export interface WorkbenchTasksController {
  tasks: DailyTask[];
  taskRunItems: TaskRunItem[];
  runStates: Record<string, TaskRunState>;
  history: TaskHistoryItem[];
  loading: boolean;
  error: string | null;
  handleClick: (task: DailyTask) => void;
  handleResume: (taskId: string, threadId: string, resumeValue: string) => void;
  handleCancelInterrupt: (taskId: string) => void;
}

export function useWorkbenchTasks(symbol: string, sessionId: string): WorkbenchTasksController {
  const { toast } = useToast();
  const watchlist = useDashboardStore((state) => state.watchlist ?? []);
  const watchlistSymbols = useMemo(
    () => watchlist.map((item) => item.symbol).filter(Boolean),
    [watchlist],
  );
  const effectiveWatchlist = useMemo(() => {
    if (watchlistSymbols.length > 0) return watchlistSymbols;
    const normalized = symbol.trim().toUpperCase();
    return normalized ? [normalized] : [];
  }, [symbol, watchlistSymbols]);
  const watchlistKey = effectiveWatchlist.join(',');

  const [tasks, setTasks] = useState<DailyTask[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const lastErrorRef = useRef<string | null>(null);

  const {
    runStates,
    setRunStates,
    history,
    updateRun,
    runStatesRef,
    titlesRef,
  } = useTaskPersistence(sessionId);
  const { handleClick, handleResume, handleCancelInterrupt } = useTaskExecution({
    symbol,
    sessionId,
    runStatesRef,
    titlesRef,
    updateRun,
  });

  useEffect(() => {
    titlesRef.current = Object.fromEntries(tasks.map((task) => [task.id, task.title]));
  }, [tasks, titlesRef]);

  useEffect(() => {
    if (!sessionId) {
      setTasks([]);
      setError(null);
      return undefined;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);

    void apiClient.getDailyTasks({
      session_id: sessionId,
      watchlist: effectiveWatchlist,
    }).then((response) => {
      if (cancelled) return;
      const nextTasks = Array.isArray(response.tasks) ? response.tasks : [];
      setTasks(nextTasks);
      setRunStates((previous) => {
        const next: Record<string, TaskRunState> = {};
        for (const task of nextTasks) {
          const existing = previous[task.id];
          const taskDefault = toRunStateFromTask(task);
          next[task.id] = withExpiration({
            ...taskDefault,
            ...(existing ?? {}),
            reportId: existing?.reportId ?? task.report_id ?? taskDefault.reportId,
            expiresAt: task.expires_at ?? existing?.expiresAt ?? null,
            status: task.status === 'expired'
              ? 'expired'
              : existing?.status === 'running'
                ? 'running'
                : existing?.status === 'interrupted'
                  ? 'interrupted'
                  : existing?.status === 'done' || task.status === 'done'
                    ? 'done'
                    : 'pending',
            progress: existing?.status === 'done' || task.status === 'done'
              ? 100
              : (existing?.progress ?? 0),
          });
        }
        return next;
      });
    }).catch((reason: unknown) => {
      if (!cancelled) setError(reason instanceof Error ? reason.message : 'Failed to load tasks');
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });

    return () => {
      cancelled = true;
    };
    // effectiveWatchlist is represented by the stable primitive key.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, setRunStates, watchlistKey]);

  useEffect(() => {
    if (!error) {
      lastErrorRef.current = null;
      return;
    }
    if (lastErrorRef.current === error) return;
    lastErrorRef.current = error;
    toast({ type: 'error', title: '任务加载失败', message: error });
  }, [error, toast]);

  const taskRunItems = useMemo(
    () => selectTaskRunItems(tasks, runStates),
    [runStates, tasks],
  );

  return {
    tasks,
    taskRunItems,
    runStates,
    history,
    loading,
    error,
    handleClick,
    handleResume,
    handleCancelInterrupt,
  };
}
