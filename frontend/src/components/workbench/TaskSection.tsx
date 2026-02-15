import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertTriangle, BarChart2, CheckCircle2, FileSearch,
  ListTodo, Loader2, Newspaper, PauseCircle, Shield,
  Sparkles, TrendingUp, XCircle,
} from 'lucide-react';

import { apiClient } from '../../api/client';
import type { DailyTask, ExecuteRequest } from '../../api/client';
import { useStore } from '../../store/useStore';
import { Card } from '../ui/Card';
import { InterruptCard } from '../execution/InterruptCard';

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface TaskSectionProps {
  symbol: string;
  onNavigateToChat?: () => void;
}

type TaskRunStatus = 'idle' | 'running' | 'done' | 'error' | 'interrupted';

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
}

const INITIAL_RUN_STATE: TaskRunState = {
  status: 'idle',
  step: null,
  progress: 0,
  reportId: null,
  error: null,
  interruptData: null,
};

/* ------------------------------------------------------------------ */
/*  Icon registry — maps backend icon names to Lucide components       */
/* ------------------------------------------------------------------ */

const ICON_MAP: Record<string, React.FC<{ size?: number; className?: string }>> = {
  AlertTriangle,
  FileSearch,
  Newspaper,
  Sparkles,
  Shield,
  TrendingUp,
  BarChart2,
};

/* ------------------------------------------------------------------ */
/*  TaskSection                                                        */
/* ------------------------------------------------------------------ */

// eslint-disable-next-line @typescript-eslint/no-unused-vars
function TaskSection(_props: TaskSectionProps) {
  const navigate = useNavigate();
  const sessionId = useStore((s) => s.sessionId);

  // Tasks from API
  const [tasks, setTasks] = useState<DailyTask[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);

  // Per-task execution state (keyed by task.id)
  const [runStates, setRunStates] = useState<Record<string, TaskRunState>>({});
  const abortRef = useRef<Record<string, AbortController>>({});

  /* ---- Fetch tasks from API ---- */
  useEffect(() => {
    if (!sessionId) return;

    let cancelled = false;
    setIsLoading(true);
    setFetchError(null);

    apiClient
      .getDailyTasks({
        session_id: sessionId,
      })
      .then((res) => {
        if (!cancelled) {
          setTasks(res.tasks);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          const message = err instanceof Error ? err.message : 'Failed to load tasks';
          setFetchError(message);
        }
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  /* ---- Update run state immutably ---- */
  const updateRun = useCallback(
    (taskId: string, patch: Partial<TaskRunState>) => {
      setRunStates((prev) => ({
        ...prev,
        [taskId]: { ...(prev[taskId] || INITIAL_RUN_STATE), ...patch },
      }));
    },
    [],
  );

  /* ---- Execute a task in-place via SSE ---- */
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
        .executeAgent(request, {
          onThinking: (step: any) => {
            const message = typeof step === 'string' ? step : (step?.message || step?.stage || '执行中...');
            updateRun(task.id, { step: message, progress: Math.min(90, (runStates[task.id]?.progress || 10) + 10) });
          },
          onToken: () => {
            updateRun(task.id, { step: '生成报告...', progress: 85 });
          },
          onDone: (report?: any) => {
            const reportId = report?.report_id || null;
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
        }, { signal: controller.signal })
        .catch((err: unknown) => {
          if (controller.signal.aborted) return;
          const message = err instanceof Error ? err.message : 'Execution failed';
          updateRun(task.id, { status: 'error', step: null, error: message });
        });
    },
    [sessionId, updateRun, runStates],
  );

  /* ---- Resume an interrupted task ---- */
  const handleResume = useCallback(
    (taskId: string, threadId: string, resumeValue: string) => {
      updateRun(taskId, { status: 'running', step: '恢复执行...', interruptData: null });

      apiClient
        .resumeExecution(
          { thread_id: threadId, resume_value: resumeValue, session_id: sessionId, source: 'workbench_resume' },
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
              updateRun(taskId, { status: 'interrupted', step: data.prompt ?? '等待确认...', interruptData: data });
            },
          },
        )
        .catch((err: unknown) => {
          const message = err instanceof Error ? err.message : 'Resume failed';
          updateRun(taskId, { status: 'error', step: null, error: message });
        });
    },
    [sessionId, updateRun],
  );

  /* ---- Cancel an interrupted task ---- */
  const handleCancelInterrupt = useCallback(
    (taskId: string) => {
      updateRun(taskId, { status: 'idle', step: null, interruptData: null });
    },
    [updateRun],
  );

  /* ---- Handle task click ---- */
  const handleClick = useCallback(
    (task: DailyTask) => {
      const run = runStates[task.id];

      // If done → navigate to report
      if (run?.status === 'done' && run.reportId) {
        navigate(`/chat?report_id=${encodeURIComponent(run.reportId)}`);
        return;
      }

      // If already running or interrupted → ignore
      if (run?.status === 'running' || run?.status === 'interrupted') return;

      // If has execution_params → execute in-place
      if (task.execution_params) {
        executeTask(task);
        return;
      }

      // Otherwise → navigate
      navigate(task.action_url);
    },
    [runStates, navigate, executeTask],
  );

  /* ---- Cleanup abort controllers on unmount ---- */
  useEffect(() => {
    const refs = abortRef.current;
    return () => {
      Object.values(refs).forEach((c) => c.abort());
    };
  }, []);

  /* ---- Render ---- */
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
        <div className="text-xs text-red-500 py-2">加载失败: {fetchError}</div>
      )}

      <div className="space-y-1.5">
        {!isLoading && tasks.length === 0 && !fetchError && (
          <div className="text-xs text-fin-muted py-2">暂无建议任务</div>
        )}

        {tasks.map((task) => {
          const IconComponent = ICON_MAP[task.icon] || ListTodo;
          const run = runStates[task.id] || INITIAL_RUN_STATE;
          const isRunning = run.status === 'running';
          const isDone = run.status === 'done';
          const isError = run.status === 'error';
          const isInterrupted = run.status === 'interrupted';
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
                          : 'text-fin-text-secondary hover:bg-fin-hover hover:text-fin-text'
                }`}
              >
                {/* Icon — swap based on state */}
                {isRunning ? (
                  <Loader2 size={14} className="animate-spin shrink-0 text-blue-500" />
                ) : isDone ? (
                  <CheckCircle2 size={14} className="shrink-0 text-emerald-500" />
                ) : isError ? (
                  <XCircle size={14} className="shrink-0 text-red-500" />
                ) : isInterrupted ? (
                  <PauseCircle size={14} className="shrink-0 text-amber-500" />
                ) : (
                  <IconComponent
                    size={14}
                    className="text-fin-muted group-hover:text-fin-primary shrink-0 transition-colors"
                  />
                )}

                <span className="truncate flex-1">
                  {isDone && run.reportId ? '查看报告' : isInterrupted ? '等待确认' : task.title}
                </span>

                {/* Executable badge */}
                {isExecutable && run.status === 'idle' && (
                  <span className="ml-auto px-1.5 py-0.5 rounded text-2xs bg-blue-100 text-blue-600 dark:bg-blue-900/30 dark:text-blue-300 shrink-0">
                    执行
                  </span>
                )}
              </button>

              {/* Progress bar for running tasks */}
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

              {/* InterruptCard for interrupted tasks */}
              {isInterrupted && run.interruptData && (
                <div className="mt-2">
                  <InterruptCard
                    data={run.interruptData}
                    onResume={(threadId, resumeValue) => handleResume(task.id, threadId, resumeValue)}
                    onCancel={() => handleCancelInterrupt(task.id)}
                  />
                </div>
              )}

              {/* Error message */}
              {isError && run.error && (
                <div className="px-2 text-2xs text-red-400 truncate" title={run.error}>
                  {run.error}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </Card>
  );
}

export { TaskSection };
export type { TaskSectionProps };
