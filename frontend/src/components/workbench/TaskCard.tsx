/**
 * TaskCard.tsx
 *
 * 单个任务卡片的渲染组件，从 TaskSection 中提取。
 * 包含任务按钮、进度条、中断确认卡片、错误和过期提示。
 */
import {
  CheckCircle2,
  Clock3,
  ListTodo,
  Loader2,
  PauseCircle,
  XCircle,
} from 'lucide-react';

import type { DailyTask } from '../../api/client';
import { InterruptCard } from '../execution/InterruptCard';
import type { TaskRunState } from './taskStateMachine';
import { ICON_MAP, toRunStateFromTask } from './taskStateMachine';

interface TaskCardProps {
  task: DailyTask;
  run: TaskRunState | undefined;
  onClick: (task: DailyTask) => void;
  onResume: (taskId: string, threadId: string, resumeValue: string) => void;
  onCancelInterrupt: (taskId: string) => void;
}

function TaskCard({ task, run: runProp, onClick, onResume, onCancelInterrupt }: TaskCardProps) {
  const IconComponent = ICON_MAP[task.icon] || ListTodo;
  const run = runProp || toRunStateFromTask(task);
  const isRunning = run.status === 'running';
  const isDone = run.status === 'done';
  const isError = run.status === 'error';
  const isInterrupted = run.status === 'interrupted';
  const isExpired = run.status === 'expired';
  const isPending = run.status === 'pending';
  const isExecutable = !!task.execution_params;

  return (
    <div className="space-y-0.5">
      <button
        type="button"
        onClick={() => onClick(task)}
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
            onResume={(threadId, resumeValue) => onResume(task.id, threadId, resumeValue)}
            onCancel={() => onCancelInterrupt(task.id)}
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
}

export { TaskCard };
export type { TaskCardProps };
