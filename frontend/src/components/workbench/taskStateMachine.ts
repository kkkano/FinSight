/**
 * taskStateMachine.ts
 *
 * TaskSection 的纯函数与类型定义。
 * 包含所有与任务运行状态相关的类型、常量、序列化/反序列化工具。
 * 不依赖任何 React API，便于独立测试。
 */
import type React from 'react';
import {
  AlertTriangle,
  BarChart2,
  FileSearch,
  ListTodo,
  Newspaper,
  Shield,
  Sparkles,
  TrendingUp,
} from 'lucide-react';

import type { DailyTask } from '../../api/client';

/* ------------------------------------------------------------------ */
/*  类型定义                                                           */
/* ------------------------------------------------------------------ */

export type TaskRunStatus = 'pending' | 'running' | 'done' | 'error' | 'interrupted' | 'expired';

export interface InterruptInfo {
  thread_id: string;
  prompt?: string;
  options?: string[];
  plan_summary?: string;
  required_agents?: string[];
}

export interface TaskRunState {
  status: TaskRunStatus;
  step: string | null;
  progress: number;
  reportId: string | null;
  error: string | null;
  interruptData: InterruptInfo | null;
  updatedAt: string;
  expiresAt: string | null;
}

export interface TaskHistoryItem {
  taskId: string;
  title: string;
  status: TaskRunStatus;
  reportId: string | null;
  error: string | null;
  at: string;
}

export interface PersistedTaskSectionState {
  runs: Record<string, TaskRunState>;
  history: TaskHistoryItem[];
}

/* ------------------------------------------------------------------ */
/*  常量                                                               */
/* ------------------------------------------------------------------ */

export const STORAGE_PREFIX = 'finsight-workbench-task-state';
export const HISTORY_MAX = 30;

export const HISTORY_STATUS_LABEL: Record<TaskRunStatus, string> = {
  pending: '待执行',
  running: '执行中',
  done: '已完成',
  error: '失败',
  interrupted: '已中断',
  expired: '已过期',
};

export const TERMINAL_STATUSES = new Set<TaskRunStatus>([
  'done',
  'error',
  'interrupted',
  'expired',
]);

export const ICON_MAP: Record<string, React.FC<{ size?: number; className?: string }>> = {
  AlertTriangle,
  FileSearch,
  Newspaper,
  Sparkles,
  Shield,
  TrendingUp,
  BarChart2,
};

/* ------------------------------------------------------------------ */
/*  纯函数                                                             */
/* ------------------------------------------------------------------ */

export const buildStorageKey = (sessionId: string): string =>
  `${STORAGE_PREFIX}:${sessionId}`;

export const nowIso = (): string => new Date().toISOString();

export const createDefaultRunState = (): TaskRunState => ({
  status: 'pending',
  step: null,
  progress: 0,
  reportId: null,
  error: null,
  interruptData: null,
  updatedAt: nowIso(),
  expiresAt: null,
});

export const parseDateMs = (value?: string | null): number | null => {
  if (!value) return null;
  const ms = Date.parse(value);
  return Number.isNaN(ms) ? null : ms;
};

/** 检查过期状态，如果任务已过期且不在运行中则标记为 expired */
export const withExpiration = (run: TaskRunState): TaskRunState => {
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

/** 从后端 DailyTask 转换为前端 TaskRunState */
export const toRunStateFromTask = (task: DailyTask): TaskRunState => {
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

/** 从 localStorage 加载持久化状态 */
export const loadPersistedState = (sessionId: string): PersistedTaskSectionState => {
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

/** 保存持久化状态到 localStorage */
export const savePersistedState = (sessionId: string, state: PersistedTaskSectionState): void => {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(buildStorageKey(sessionId), JSON.stringify(state));
  } catch {
    // 忽略 quota/storage 错误
  }
};

/** 格式化 ISO 时间字符串为 HH:MM */
export const formatTime = (iso: string): string => {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '--:--';
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
};
