/**
 * TaskSection.tsx
 *
 * 工作台"今日任务"面板。
 *
 * 重构后只负责：
 * 1. 组合 useTaskPersistence + useTaskExecution hooks
 * 2. 从后端获取任务列表
 * 3. 渲染任务卡片列表 + 执行历史
 *
 * 纯函数/类型/常量  → taskStateMachine.ts
 * 持久化逻辑        → useTaskPersistence.ts
 * SSE 执行逻辑     → useTaskExecution.ts
 * 单卡片渲染        → TaskCard.tsx
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { ListTodo, Loader2 } from 'lucide-react';

import { apiClient } from '../../api/client';
import type { DailyTask } from '../../api/client';
import { useStore } from '../../store/useStore';
import { useDashboardStore } from '../../store/dashboardStore';
import { Card } from '../ui/Card';
import { useToast } from '../ui';

import {
  HISTORY_STATUS_LABEL,
  formatTime,
  toRunStateFromTask,
  withExpiration,
} from './taskStateMachine';
import { TaskCard } from './TaskCard';
import { useTaskPersistence } from '../../hooks/useTaskPersistence';
import { useTaskExecution } from '../../hooks/useTaskExecution';

/* ------------------------------------------------------------------ */
/*  Props                                                              */
/* ------------------------------------------------------------------ */

interface TaskSectionProps {
  symbol: string;
  onNavigateToChat?: () => void;
}

/* ------------------------------------------------------------------ */
/*  组件                                                               */
/* ------------------------------------------------------------------ */

function TaskSection({ symbol }: TaskSectionProps) {
  const { toast } = useToast();
  const sessionId = useStore((s) => s.sessionId);
  const watchlist = useDashboardStore((s) => s.watchlist ?? []);

  // --- 有效 watchlist 计算 ---
  const watchlistSymbols = useMemo(
    () => watchlist.map((item) => item.symbol).filter(Boolean),
    [watchlist],
  );
  const effectiveWatchlist = useMemo(() => {
    if (watchlistSymbols.length > 0) return watchlistSymbols;
    return symbol ? [symbol.trim().toUpperCase()] : [];
  }, [symbol, watchlistSymbols]);
  const watchlistKey = useMemo(() => effectiveWatchlist.join(','), [effectiveWatchlist]);

  // --- 任务列表状态 ---
  const [tasks, setTasks] = useState<DailyTask[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const lastErrorRef = useRef<string | null>(null);

  // --- 持久化 hook ---
  const {
    runStates,
    setRunStates,
    history,
    updateRun,
    runStatesRef,
    titlesRef,
  } = useTaskPersistence(sessionId);

  // --- 执行 hook ---
  const { handleClick, handleResume, handleCancelInterrupt } = useTaskExecution({
    symbol,
    sessionId,
    runStatesRef,
    titlesRef,
    updateRun,
  });

  // --- 同步 titlesRef ---
  useEffect(() => {
    const map: Record<string, string> = {};
    for (const task of tasks) {
      map[task.id] = task.title;
    }
    titlesRef.current = map;
  }, [tasks, titlesRef]);

  // --- 获取任务列表 ---
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
          const next: Record<string, typeof prev[string]> = {};
          for (const task of nextTasks) {
            const existing = prev[task.id];
            const taskDefault = toRunStateFromTask(task);
            const merged = withExpiration({
              ...taskDefault,
              ...(existing ?? {}),
              reportId: existing?.reportId ?? task.report_id ?? taskDefault.reportId,
              expiresAt: task.expires_at ?? existing?.expiresAt ?? null,
              status: (() => {
                if (task.status === 'expired') return 'expired' as const;
                if (existing?.status === 'running') return 'running' as const;
                if (existing?.status === 'interrupted') return 'interrupted' as const;
                if (existing?.status === 'done') return 'done' as const;
                if (task.status === 'done') return 'done' as const;
                return 'pending' as const;
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
  }, [sessionId, watchlistKey, effectiveWatchlist, setRunStates]);

  // --- 错误 toast（去重） ---
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

  // --- 渲染 ---
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

        {tasks.map((task) => (
          <TaskCard
            key={task.id}
            task={task}
            run={runStates[task.id]}
            onClick={handleClick}
            onResume={handleResume}
            onCancelInterrupt={handleCancelInterrupt}
          />
        ))}
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
