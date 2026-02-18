import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertTriangle,
  BarChart2,
  CheckCircle2,
  Clock3,
  FileSearch,
  ListTodo,
  Loader2,
  Newspaper,
  PauseCircle,
  Shield,
  Sparkles,
  TrendingUp,
  XCircle,
} from 'lucide-react';

import { apiClient } from '../../api/client';
import type { DailyTask, ExecuteRequest } from '../../api/client';
import { useStore } from '../../store/useStore';
import { useDashboardStore } from '../../store/dashboardStore';
import { Card } from '../ui/Card';
import { useToast } from '../ui';
import { InterruptCard } from '../execution/InterruptCard';

interface TaskSectionProps {
  symbol: string;
  onNavigateToChat?: () => void;
}

type TaskRunStatus = 'pending' | 'running' | 'done' | 'error' | 'interrupted' | 'expired';

interface InterruptInfo {
  thread_id: string;
  prompt?: string;
  options?: string[];
  plan_summary?: string;
  required_agents?: string[];
}

interface TaskRunState {
  status: TaskRunStatus;
  step: string | null;
  progress: number;
  reportId: string | null;
  error: string | null;
  interruptData: InterruptInfo | null;
  updatedAt: string;
  expiresAt: string | null;
}

interface TaskHistoryItem {
  taskId: string;
  title: string;
  status: TaskRunStatus;
  reportId: string | null;
  error: string | null;
  at: string;
}

interface PersistedTaskSectionState {
  runs: Record<string, TaskRunState>;
  history: TaskHistoryItem[];
}

const STORAGE_PREFIX = 'finsight-workbench-task-state';
const HISTORY_MAX = 30;
const HISTORY_STATUS_LABEL: Record<TaskRunStatus, string> = {
  pending: '待执行',
  running: '执行中',
  done: '已完成',
  error: '失败',
  interrupted: '已中断',
  expired: '已过期',
};

const TERMINAL_STATUSES = new Set<TaskRunStatus>([
  'done',
  'error',
  'interrupted',
  'expired',
]);

const ICON_MAP: Record<string, React.FC<{ size?: number; className?: string }>> = {
  AlertTriangle,
  FileSearch,
  Newspaper,
  Sparkles,
  Shield,
  TrendingUp,
  BarChart2,
};

const buildStorageKey = (sessionId: string) => `${STORAGE_PREFIX}:${sessionId}`;

const nowIso = () => new Date().toISOString();

const createDefaultRunState = (): TaskRunState => ({
  status: 'pending',
  step: null,
  progress: 0,
  reportId: null,
  error: null,
  interruptData: null,
  updatedAt: nowIso(),
  expiresAt: null,
});

const parseDateMs = (value?: string | null): number | null => {
  if (!value) return null;
  const ms = Date.parse(value);
  return Number.isNaN(ms) ? null : ms;
};

const withExpiration = (run: TaskRunState): TaskRunState => {
  const expiresMs = parseDateMs(run.expiresAt);
  if (expiresMs === null) return run;
  if (Date.now() <= expiresMs) return run;
  if (run.status === 'running' || run.status === 'expired') return run;
  return {
    ...run,
    status: 'expired',
    step: '任务已过期，请刷新任务列表',
    updatedAt: nowIso(),
  };
};

const toRunStateFromTask = (task: DailyTask): TaskRunState => {
  const status = task.status ?? 'pending';
  const base = createDefaultRunState();
  const next: TaskRunState = {
    ...base,
    status: status === 'done' || status === 'expired' ? status : 'pending',
    reportId: task.report_id ?? null,
    progress: status === 'done' ? 100 : 0,
    expiresAt: task.expires_at ?? null,
  };
  return withExpiration(next);
};

const loadPersistedState = (sessionId: string): PersistedTaskSectionState => {
  if (typeof window === 'undefined') return { runs: {}, history: [] };
  try {
    const raw = window.localStorage.getItem(buildStorageKey(sessionId));
    if (!raw) return { runs: {}, history: [] };
    const parsed = JSON.parse(raw) as Partial<PersistedTaskSectionState>;
    const runs = parsed.runs && typeof parsed.runs === 'object' ? parsed.runs : {};
    const history = Array.isArray(parsed.history) ? parsed.history : [];
    return { runs: runs as Record<string, TaskRunState>, history: history as TaskHistoryItem[] };
  } catch {
    return { runs: {}, history: [] };
  }
};

const savePersistedState = (sessionId: string, state: PersistedTaskSectionState): void => {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(buildStorageKey(sessionId), JSON.stringify(state));
  } catch {
    // ignore quota/storage errors
  }
};

const formatTime = (iso: string): string => {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '--:--';
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
};

function TaskSection({ symbol }: TaskSectionProps) {
  const navigate = useNavigate();
  const { toast } = useToast();
  const sessionId = useStore((s) => s.sessionId);
  const addRawEvent = useStore((s) => s.addRawEvent);
  const traceRawEnabled = useStore((s) => s.traceRawEnabled);
  const watchlist = useDashboardStore((s) => s.watchlist ?? []);
  const watchlistSymbols = useMemo(
    () => watchlist.map((item) => item.symbol).filter(Boolean),
    [watchlist],
  );
  const effectiveWatchlist = useMemo(() => {
    if (watchlistSymbols.length > 0) return watchlistSymbols;
    return symbol ? [symbol.trim().toUpperCase()] : [];
  }, [symbol, watchlistSymbols]);
  const watchlistKey = useMemo(() => effectiveWatchlist.join(','), [effectiveWatchlist]);

  const [tasks, setTasks] = useState<DailyTask[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [runStates, setRunStates] = useState<Record<string, TaskRunState>>({});
  const [history, setHistory] = useState<TaskHistoryItem[]>([]);

  const runStatesRef = useRef<Record<string, TaskRunState>>({});
  const abortRef = useRef<Record<string, AbortController>>({});
  const titlesRef = useRef<Record<string, string>>({});
  const lastErrorRef = useRef<string | null>(null);
  const prevStatusRef = useRef<Record<string, TaskRunStatus>>({});

  useEffect(() => {
    runStatesRef.current = runStates;
  }, [runStates]);

  useEffect(() => {
    if (!sessionId) return;
    const persisted = loadPersistedState(sessionId);
    const hydratedRuns: Record<string, TaskRunState> = {};
    const hydratedStatusMap: Record<string, TaskRunStatus> = {};
    for (const [taskId, run] of Object.entries(persisted.runs || {})) {
      const base = {
        ...createDefaultRunState(),
        ...run,
        updatedAt: run.updatedAt || nowIso(),
      };
      const hydrated = withExpiration(base);
      hydratedRuns[taskId] = hydrated;
      hydratedStatusMap[taskId] = hydrated.status;
    }
    prevStatusRef.current = hydratedStatusMap;
    setRunStates(hydratedRuns);
    setHistory((persisted.history || []).slice(0, HISTORY_MAX));
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId) return;
    savePersistedState(sessionId, {
      runs: runStates,
      history: history.slice(0, HISTORY_MAX),
    });
  }, [sessionId, runStates, history]);

  useEffect(() => {
    const map: Record<string, string> = {};
    for (const task of tasks) {
      map[task.id] = task.title;
    }
    titlesRef.current = map;
  }, [tasks]);

  useEffect(() => {
    if (!sessionId) return;

    let cancelled = false;
    setIsLoading(true);
    setFetchError(null);

    apiClient
      .getDailyTasks({
        session_id: sessionId,
        watchlist: effectiveWatchlist,
      })
      .then((res) => {
        if (cancelled) return;
        const nextTasks = Array.isArray(res.tasks) ? res.tasks : [];
        setTasks(nextTasks);
        setRunStates((prev) => {
          const next: Record<string, TaskRunState> = {};
          for (const task of nextTasks) {
            const existing = prev[task.id];
            const taskDefault = toRunStateFromTask(task);
            const merged: TaskRunState = withExpiration({
              ...taskDefault,
              ...(existing ?? {}),
              reportId: existing?.reportId ?? task.report_id ?? taskDefault.reportId,
              expiresAt: task.expires_at ?? existing?.expiresAt ?? null,
              status: (() => {
                if (task.status === 'expired') return 'expired';
                if (existing?.status === 'running') return 'running';
                if (existing?.status === 'interrupted') return 'interrupted';
                if (existing?.status === 'done') return 'done';
                if (task.status === 'done') return 'done';
                return 'pending';
              })(),
              progress: existing?.status === 'done' || task.status === 'done' ? 100 : (existing?.progress ?? 0),
            });
            next[task.id] = merged;
          }
          return next;
        });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const message = err instanceof Error ? err.message : 'Failed to load tasks';
        setFetchError(message);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [sessionId, watchlistKey, effectiveWatchlist]);

  useEffect(() => {
    if (!fetchError) {
      lastErrorRef.current = null;
      return;
    }
    if (lastErrorRef.current === fetchError) return;
    lastErrorRef.current = fetchError;
    toast({
      type: 'error',
      title: '任务加载失败',
      message: fetchError,
    });
  }, [fetchError, toast]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setRunStates((prev) => {
        let changed = false;
        const next: Record<string, TaskRunState> = {};
        for (const [taskId, run] of Object.entries(prev)) {
          const expired = withExpiration(run);
          if (expired.status !== run.status || expired.step !== run.step || expired.updatedAt !== run.updatedAt) {
            changed = true;
          }
          next[taskId] = expired;
        }
        return changed ? next : prev;
      });
    }, 30_000);
    return () => {
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    const previous = prevStatusRef.current;
    const additions: TaskHistoryItem[] = [];
    const nextStatusMap: Record<string, TaskRunStatus> = {};

    for (const [taskId, run] of Object.entries(runStates)) {
      const prevStatus = previous[taskId];
      nextStatusMap[taskId] = run.status;
      if (run.status === prevStatus) continue;
      if (!TERMINAL_STATUSES.has(run.status)) continue;
      additions.push({
        taskId,
        title: titlesRef.current[taskId] || taskId,
        status: run.status,
        reportId: run.reportId,
        error: run.error,
        at: run.updatedAt || nowIso(),
      });
    }

    prevStatusRef.current = nextStatusMap;
    if (additions.length > 0) {
      setHistory((prev) => {
        const merged = [...additions.reverse(), ...prev];
        const seen = new Set<string>();
        const deduped: TaskHistoryItem[] = [];
        for (const item of merged) {
          const key = `${item.taskId}:${item.status}:${item.reportId || ''}:${item.at}`;
          if (seen.has(key)) continue;
          seen.add(key);
          deduped.push(item);
          if (deduped.length >= HISTORY_MAX) break;
        }
        return deduped;
      });
    }
  }, [runStates]);

  const updateRun = useCallback((taskId: string, patch: Partial<TaskRunState>) => {
    setRunStates((prev) => {
      const current = prev[taskId] || createDefaultRunState();
      const next = withExpiration({
        ...current,
        ...patch,
        updatedAt: nowIso(),
      });
      return {
        ...prev,
        [taskId]: next,
      };
    });
  }, []);

  const executeTask = useCallback(
    (task: DailyTask) => {
      if (!task.execution_params) return;

      const controller = new AbortController();
      abortRef.current[task.id] = controller;

      const request: ExecuteRequest = {
        ...task.execution_params,
        session_id: sessionId,
        source: 'workbench_task',
      };

      updateRun(task.id, {
        status: 'running',
        step: '准备中...',
        progress: 5,
        error: null,
        reportId: null,
        interruptData: null,
      });

      apiClient
        .executeAgent(
          request,
          {
            onThinking: (step: any) => {
              const message = typeof step === 'string' ? step : (step?.message || step?.stage || '执行中...');
              const current = runStatesRef.current[task.id] || createDefaultRunState();
              updateRun(task.id, {
                step: message,
                progress: Math.min(90, Math.max(10, current.progress + 10)),
              });
            },
            onToken: () => {
              updateRun(task.id, { step: '生成报告...', progress: 85 });
            },
            onDone: (report?: any) => {
              const reportId = report?.report_id || task.report_id || null;
              updateRun(task.id, { status: 'done', step: null, progress: 100, reportId });
            },
            onError: (error: string) => {
              updateRun(task.id, { status: 'error', step: null, error });
            },
            onInterrupt: (data) => {
              updateRun(task.id, {
                status: 'interrupted',
                step: data.prompt ?? '等待确认...',
                interruptData: data,
              });
            },
            onRawEvent: (event) => {
              addRawEvent(event);
            },
          },
          { signal: controller.signal, traceRawEnabled },
        )
        .then(() => {
          const current = runStatesRef.current[task.id];
          if (current?.status === 'running') {
            updateRun(task.id, {
              status: 'error',
              step: null,
              error: 'Execution stream ended unexpectedly (missing done event)',
            });
          }
        })
        .catch((err: unknown) => {
          if (controller.signal.aborted) return;
          const message = err instanceof Error ? err.message : 'Execution failed';
          updateRun(task.id, { status: 'error', step: null, error: message });
        });
    },
    [addRawEvent, sessionId, traceRawEnabled, updateRun],
  );

  const handleResume = useCallback(
    (taskId: string, threadId: string, resumeValue: string) => {
      updateRun(taskId, { status: 'running', step: '恢复执行...', interruptData: null });

      apiClient
        .resumeExecution(
          {
            thread_id: threadId,
            resume_value: resumeValue,
            session_id: sessionId,
            source: 'workbench_resume',
          },
          {
            onThinking: (step: any) => {
              const message = typeof step === 'string' ? step : (step?.message || step?.stage || '执行中...');
              updateRun(taskId, { step: message });
            },
            onToken: () => {
              updateRun(taskId, { step: '生成报告...', progress: 85 });
            },
            onDone: (report?: any) => {
              const reportId = report?.report_id || null;
              updateRun(taskId, { status: 'done', step: null, progress: 100, reportId });
            },
            onError: (error: string) => {
              updateRun(taskId, { status: 'error', step: null, error });
            },
            onInterrupt: (data) => {
              updateRun(taskId, {
                status: 'interrupted',
                step: data.prompt ?? '等待确认...',
                interruptData: data,
              });
            },
            onRawEvent: (event) => {
              addRawEvent(event);
            },
          },
          { traceRawEnabled },
        )
        .then(() => {
          const current = runStatesRef.current[taskId];
          if (current?.status === 'running') {
            updateRun(taskId, {
              status: 'error',
              step: null,
              error: 'Resume stream ended unexpectedly (missing done event)',
            });
          }
        })
        .catch((err: unknown) => {
          const message = err instanceof Error ? err.message : 'Resume failed';
          updateRun(taskId, { status: 'error', step: null, error: message });
        });
    },
    [addRawEvent, sessionId, traceRawEnabled, updateRun],
  );

  const handleCancelInterrupt = useCallback(
    (taskId: string) => {
      updateRun(taskId, { status: 'pending', step: null, interruptData: null, progress: 0 });
    },
    [updateRun],
  );

  const handleClick = useCallback(
    (task: DailyTask) => {
      const run = runStatesRef.current[task.id] || toRunStateFromTask(task);

      if (run.status === 'done' && run.reportId) {
        navigate(`/chat?report_id=${encodeURIComponent(run.reportId)}`);
        return;
      }

      if (run.status === 'expired') {
        toast({
          type: 'warning',
          title: '任务已过期',
          message: '请等待下一轮任务刷新或重新发起分析',
        });
        return;
      }

      if (run.status === 'running' || run.status === 'interrupted') return;

      if (task.execution_params) {
        executeTask(task);
        return;
      }

      if (task.action_url) {
        navigate(task.action_url);
      }
    },
    [executeTask, navigate, toast],
  );

  useEffect(() => {
    const refs = abortRef.current;
    return () => {
      Object.values(refs).forEach((controller) => controller.abort());
    };
  }, []);

  const recentHistory = history.slice(0, 5);

  return (
    <Card className="p-4">
      <div className="flex items-center gap-2 mb-3 text-fin-text font-semibold text-sm">
        <ListTodo size={16} className="text-fin-primary" />
        今日任务
      </div>

      {isLoading && (
        <div className="flex items-center gap-2 text-xs text-fin-muted py-2">
          <Loader2 size={12} className="animate-spin" />
          加载中...
        </div>
      )}

      {fetchError && !isLoading && (
        <div className="text-xs text-fin-danger py-2">加载失败: {fetchError}</div>
      )}

      <div className="space-y-1.5">
        {!isLoading && tasks.length === 0 && !fetchError && (
          <div className="text-xs text-fin-muted py-2">暂无建议任务</div>
        )}

        {tasks.map((task) => {
          const IconComponent = ICON_MAP[task.icon] || ListTodo;
          const run = runStates[task.id] || toRunStateFromTask(task);
          const isRunning = run.status === 'running';
          const isDone = run.status === 'done';
          const isError = run.status === 'error';
          const isInterrupted = run.status === 'interrupted';
          const isExpired = run.status === 'expired';
          const isPending = run.status === 'pending';
          const isExecutable = !!task.execution_params;

          return (
            <div key={task.id} className="space-y-0.5">
              <button
                type="button"
                onClick={() => handleClick(task)}
                disabled={isRunning || isInterrupted}
                className={`w-full text-left flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs transition-colors group ${
                  isRunning
                    ? 'bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-300 cursor-wait'
                    : isDone
                      ? 'bg-emerald-50 dark:bg-emerald-900/20 text-emerald-600 dark:text-emerald-300 hover:bg-emerald-100 dark:hover:bg-emerald-900/30'
                      : isError
                        ? 'bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-300 hover:bg-red-100 dark:hover:bg-red-900/30'
                        : isInterrupted
                          ? 'bg-amber-50 dark:bg-amber-900/20 text-amber-600 dark:text-amber-300 cursor-default'
                          : isExpired
                            ? 'bg-slate-100 dark:bg-slate-800/60 text-slate-500 dark:text-slate-300'
                            : 'text-fin-text-secondary hover:bg-fin-hover hover:text-fin-text'
                }`}
              >
                {isRunning ? (
                  <Loader2 size={14} className="animate-spin shrink-0 text-blue-500" />
                ) : isDone ? (
                  <CheckCircle2 size={14} className="shrink-0 text-emerald-500" />
                ) : isError ? (
                  <XCircle size={14} className="shrink-0 text-red-500" />
                ) : isInterrupted ? (
                  <PauseCircle size={14} className="shrink-0 text-amber-500" />
                ) : isExpired ? (
                  <Clock3 size={14} className="shrink-0 text-slate-500" />
                ) : (
                  <IconComponent
                    size={14}
                    className="text-fin-muted group-hover:text-fin-primary shrink-0 transition-colors"
                  />
                )}

                <span className="truncate flex-1">
                  {isDone && run.reportId ? '查看报告' : isInterrupted ? '等待确认' : isExpired ? '任务已过期' : task.title}
                </span>

                {isExecutable && isPending && (
                  <span className="ml-auto px-1.5 py-0.5 rounded text-2xs bg-blue-100 text-blue-600 dark:bg-blue-900/30 dark:text-blue-300 shrink-0">
                    待执行
                  </span>
                )}
              </button>

              {isRunning && (
                <div className="px-2">
                  <div className="flex items-center gap-2 text-2xs text-blue-500 dark:text-blue-300 mb-0.5">
                    <span className="truncate">{run.step || '处理中...'}</span>
                    <span className="shrink-0">{run.progress}%</span>
                  </div>
                  <div className="h-1 rounded-full bg-blue-100 dark:bg-blue-900/30 overflow-hidden">
                    <div
                      className="h-full rounded-full bg-blue-500 transition-all duration-300"
                      style={{ width: `${run.progress}%` }}
                    />
                  </div>
                </div>
              )}

              {isInterrupted && run.interruptData && (
                <div className="mt-2">
                  <InterruptCard
                    data={run.interruptData}
                    onResume={(threadId, resumeValue) => handleResume(task.id, threadId, resumeValue)}
                    onCancel={() => handleCancelInterrupt(task.id)}
                  />
                </div>
              )}

              {isError && run.error && (
                <div className="px-2 text-2xs text-red-400 truncate" title={run.error}>
                  {run.error}
                </div>
              )}

              {isExpired && (
                <div className="px-2 text-2xs text-slate-400">任务已过期，等待下一轮任务刷新</div>
              )}
            </div>
          );
        })}
      </div>

      {recentHistory.length > 0 && (
        <div className="mt-4 pt-3 border-t border-fin-border">
          <div className="text-2xs font-medium text-fin-text-secondary mb-2">执行历史</div>
          <div className="space-y-1">
            {recentHistory.map((item, idx) => (
              <div key={`${item.taskId}-${item.at}-${String(idx)}`} className="text-2xs text-fin-muted flex items-center gap-2">
                <span className="w-10 shrink-0">{formatTime(item.at)}</span>
                <span
                  className={`w-14 shrink-0 ${
                    item.status === 'done'
                      ? 'text-emerald-500'
                      : item.status === 'error'
                        ? 'text-red-500'
                        : item.status === 'expired'
                          ? 'text-slate-400'
                          : 'text-amber-500'
                  }`}
                >
                  {HISTORY_STATUS_LABEL[item.status] ?? item.status}
                </span>
                <span className="truncate flex-1">{item.title}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}

export { TaskSection };
export type { TaskSectionProps };
