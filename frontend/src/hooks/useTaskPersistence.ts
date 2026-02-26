/**
 * useTaskPersistence.ts
 *
 * 管理 TaskSection 的 localStorage 持久化逻辑。
 * 负责 hydration（从磁盘恢复）、自动保存、以及 updateRun 回调。
 */
import { useCallback, useEffect, useRef, useState } from 'react';

import type { TaskRunState, TaskHistoryItem, TaskRunStatus } from '../components/workbench/taskStateMachine';
import {
  HISTORY_MAX,
  TERMINAL_STATUSES,
  createDefaultRunState,
  loadPersistedState,
  nowIso,
  savePersistedState,
  withExpiration,
} from '../components/workbench/taskStateMachine';

export interface UseTaskPersistenceReturn {
  runStates: Record<string, TaskRunState>;
  setRunStates: React.Dispatch<React.SetStateAction<Record<string, TaskRunState>>>;
  history: TaskHistoryItem[];
  setHistory: React.Dispatch<React.SetStateAction<TaskHistoryItem[]>>;
  /** 局部更新某个 taskId 的运行状态 */
  updateRun: (taskId: string, patch: Partial<TaskRunState>) => void;
  /** ref 始终指向最新 runStates，供回调闭包安全读取 */
  runStatesRef: React.MutableRefObject<Record<string, TaskRunState>>;
  /** ref 用于跟踪上一次状态，驱动历史记录写入 */
  prevStatusRef: React.MutableRefObject<Record<string, TaskRunStatus>>;
  /** ref 缓存 taskId → title 映射 */
  titlesRef: React.MutableRefObject<Record<string, string>>;
}

export function useTaskPersistence(sessionId: string): UseTaskPersistenceReturn {
  const [runStates, setRunStates] = useState<Record<string, TaskRunState>>({});
  const [history, setHistory] = useState<TaskHistoryItem[]>([]);

  const runStatesRef = useRef<Record<string, TaskRunState>>({});
  const prevStatusRef = useRef<Record<string, TaskRunStatus>>({});
  const titlesRef = useRef<Record<string, string>>({});

  // 保持 ref 与 state 同步
  useEffect(() => {
    runStatesRef.current = runStates;
  }, [runStates]);

  // --- Hydration: 从 localStorage 恢复 ---
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

  // --- 自动保存到 localStorage ---
  useEffect(() => {
    if (!sessionId) return;
    savePersistedState(sessionId, {
      runs: runStates,
      history: history.slice(0, HISTORY_MAX),
    });
  }, [sessionId, runStates, history]);

  // --- 定时检查过期 ---
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

  // --- 状态变更 → 历史记录 ---
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

  // --- updateRun: 局部更新某个任务的状态 ---
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

  return {
    runStates,
    setRunStates,
    history,
    setHistory,
    updateRun,
    runStatesRef,
    prevStatusRef,
    titlesRef,
  };
}
