/**
 * useTaskExecution.ts
 *
 * 提取 TaskSection 中 executeTask / handleResume 的 SSE 执行逻辑。
 *
 * 核心改进：
 * - buildSSECallbacks() 工厂函数统一生成 onThinking/onToken/onDone/onError/onInterrupt/onRawEvent
 * - handleStreamEnd() 统一处理 .then()/.catch() 逻辑
 * - handleResume 补上了原版缺失的 AbortController
 * - executeTask 和 handleResume 共享上述工厂，消除 ~110 行重复代码
 */
import { useCallback, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';

import { apiClient } from '../api/client';
import type { DailyTask, ExecuteRequest, SSECallbacks } from '../api/client';
import { useStore } from '../store/useStore';
import { useExecutionStore } from '../store/executionStore';
import { useToast } from '../components/ui';

import type { TaskRunState } from '../components/workbench/taskStateMachine';
import { createDefaultRunState, toRunStateFromTask } from '../components/workbench/taskStateMachine';

/* ------------------------------------------------------------------ */
/*  参数类型                                                           */
/* ------------------------------------------------------------------ */

export interface UseTaskExecutionParams {
  symbol: string;
  sessionId: string;
  /** ref 始终指向最新 runStates */
  runStatesRef: React.MutableRefObject<Record<string, TaskRunState>>;
  /** ref 缓存 taskId → title */
  titlesRef: React.MutableRefObject<Record<string, string>>;
  /** 局部更新某个 taskId 的运行状态 */
  updateRun: (taskId: string, patch: Partial<TaskRunState>) => void;
}

export interface UseTaskExecutionReturn {
  executeTask: (task: DailyTask) => void;
  handleResume: (taskId: string, threadId: string, resumeValue: string) => void;
  handleCancelInterrupt: (taskId: string) => void;
  handleClick: (task: DailyTask) => void;
}

/* ------------------------------------------------------------------ */
/*  Hook 实现                                                          */
/* ------------------------------------------------------------------ */

export function useTaskExecution({
  symbol,
  sessionId,
  runStatesRef,
  titlesRef,
  updateRun,
}: UseTaskExecutionParams): UseTaskExecutionReturn {
  const navigate = useNavigate();
  const { toast } = useToast();

  // --- 从全局 store 读取所需方法 ---
  const addRawEvent = useStore((s) => s.addRawEvent);
  const traceRawEnabled = useStore((s) => s.traceRawEnabled);
  const beginExternalExecution = useExecutionStore((s) => s.beginExternalExecution);
  const ingestExternalThinking = useExecutionStore((s) => s.ingestExternalThinking);
  const ingestExternalToken = useExecutionStore((s) => s.ingestExternalToken);
  const completeExternalExecution = useExecutionStore((s) => s.completeExternalExecution);
  const interruptExternalExecution = useExecutionStore((s) => s.interruptExternalExecution);

  // --- 内部 ref ---
  const abortRef = useRef<Record<string, AbortController>>({});
  const executionRunRef = useRef<Record<string, string>>({});

  // 组件卸载时中止所有执行
  useEffect(() => {
    const refs = abortRef.current;
    return () => {
      Object.values(refs).forEach((controller) => controller.abort());
    };
  }, []);

  /* ---------------------------------------------------------------- */
  /*  ensureExecutionRun — 创建或复用 executionRunId                    */
  /* ---------------------------------------------------------------- */
  const ensureExecutionRun = useCallback(
    (taskId: string, request: ExecuteRequest, fallbackTitle: string, mode: 'start' | 'resume' = 'start') => {
      const existing = executionRunRef.current[taskId];
      const shouldReuse = mode === 'resume' && Boolean(existing);
      const runId = shouldReuse
        ? String(existing)
        : `workbench-task-${taskId}-${Date.now().toString(36)}`;

      executionRunRef.current[taskId] = runId;
      const fallbackTicker = symbol ? symbol.trim().toUpperCase() : '';
      beginExternalExecution({
        runId,
        query: request.query || fallbackTitle,
        tickers: Array.isArray(request.tickers) && request.tickers.length > 0
          ? request.tickers
          : (fallbackTicker ? [fallbackTicker] : []),
        source: request.source || (mode === 'resume' ? 'workbench_resume' : 'workbench_task'),
        outputMode: request.output_mode || 'brief',
        analysisDepth: request.analysis_depth,
      });
      return runId;
    },
    [beginExternalExecution, symbol],
  );

  /* ---------------------------------------------------------------- */
  /*  buildSSECallbacks — 统一生成 SSE 回调（消除重复代码的关键）         */
  /* ---------------------------------------------------------------- */
  const buildSSECallbacks = useCallback(
    (taskId: string, executionRunId: string): SSECallbacks => ({
      onThinking: (step: any) => {
        const message = typeof step === 'string' ? step : (step?.message || step?.stage || '执行中...');
        const current = runStatesRef.current[taskId] || createDefaultRunState();
        updateRun(taskId, {
          step: message,
          progress: Math.min(90, Math.max(10, current.progress + 10)),
        });
        ingestExternalThinking(executionRunId, step);
      },
      onToken: () => {
        ingestExternalToken(executionRunId, '');
        updateRun(taskId, { step: '生成报告...', progress: 85 });
      },
      onDone: (report?: any) => {
        const reportId = report?.report_id || null;
        updateRun(taskId, { status: 'done', step: null, progress: 100, reportId });
        completeExternalExecution({
          runId: executionRunId,
          status: 'done',
          report: report ?? null,
          meta: reportId ? { report_id: reportId } : undefined,
        });
      },
      onError: (error: string) => {
        updateRun(taskId, { status: 'error', step: null, error });
        completeExternalExecution({
          runId: executionRunId,
          status: 'error',
          error,
        });
      },
      onInterrupt: (data) => {
        interruptExternalExecution(executionRunId, data);
        updateRun(taskId, {
          status: 'interrupted',
          step: data.prompt ?? '等待确认...',
          interruptData: data,
        });
      },
      onRawEvent: (event) => {
        addRawEvent(event);
      },
    }),
    [
      addRawEvent,
      completeExternalExecution,
      ingestExternalThinking,
      ingestExternalToken,
      interruptExternalExecution,
      runStatesRef,
      updateRun,
    ],
  );

  /* ---------------------------------------------------------------- */
  /*  handleStreamEnd — 统一处理 .then()/.catch()                      */
  /* ---------------------------------------------------------------- */
  const handleStreamEnd = useCallback(
    (taskId: string, executionRunId: string, controller: AbortController, label: string) => ({
      onResolve: () => {
        const current = runStatesRef.current[taskId];
        if (current?.status === 'running') {
          const msg = `${label} stream ended unexpectedly (missing done event)`;
          updateRun(taskId, { status: 'error', step: null, error: msg });
          completeExternalExecution({
            runId: executionRunId,
            status: 'error',
            error: msg,
          });
        }
      },
      onReject: (err: unknown) => {
        if (controller.signal.aborted) return;
        const message = err instanceof Error ? err.message : `${label} failed`;
        updateRun(taskId, { status: 'error', step: null, error: message });
        completeExternalExecution({
          runId: executionRunId,
          status: 'error',
          error: message,
        });
      },
    }),
    [completeExternalExecution, runStatesRef, updateRun],
  );

  /* ---------------------------------------------------------------- */
  /*  executeTask                                                      */
  /* ---------------------------------------------------------------- */
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
      const executionRunId = ensureExecutionRun(task.id, request, task.title, 'start');

      updateRun(task.id, {
        status: 'running',
        step: '准备中...',
        progress: 5,
        error: null,
        reportId: null,
        interruptData: null,
      });

      const callbacks = buildSSECallbacks(task.id, executionRunId);
      const { onResolve, onReject } = handleStreamEnd(task.id, executionRunId, controller, 'Execution');

      apiClient
        .executeAgent(request, callbacks, { signal: controller.signal, traceRawEnabled })
        .then(onResolve)
        .catch(onReject);
    },
    [
      buildSSECallbacks,
      ensureExecutionRun,
      handleStreamEnd,
      sessionId,
      traceRawEnabled,
      updateRun,
    ],
  );

  /* ---------------------------------------------------------------- */
  /*  handleResume（已补上 AbortController）                            */
  /* ---------------------------------------------------------------- */
  const handleResume = useCallback(
    (taskId: string, threadId: string, resumeValue: string) => {
      // 补上原版缺失的 AbortController
      const controller = new AbortController();
      abortRef.current[taskId] = controller;

      updateRun(taskId, { status: 'running', step: '恢复执行...', interruptData: null });

      const request: ExecuteRequest = {
        query: titlesRef.current[taskId] || `Resume task ${taskId}`,
        tickers: symbol ? [symbol.trim().toUpperCase()] : [],
        source: 'workbench_resume',
      };
      const executionRunId = ensureExecutionRun(taskId, request, request.query, 'resume');

      const callbacks = buildSSECallbacks(taskId, executionRunId);
      const { onResolve, onReject } = handleStreamEnd(taskId, executionRunId, controller, 'Resume');

      apiClient
        .resumeExecution(
          {
            thread_id: threadId,
            resume_value: resumeValue,
            session_id: sessionId,
            source: 'workbench_resume',
          },
          callbacks,
          { traceRawEnabled, signal: controller.signal },
        )
        .then(onResolve)
        .catch(onReject);
    },
    [
      buildSSECallbacks,
      ensureExecutionRun,
      handleStreamEnd,
      sessionId,
      symbol,
      titlesRef,
      traceRawEnabled,
      updateRun,
    ],
  );

  /* ---------------------------------------------------------------- */
  /*  handleCancelInterrupt                                            */
  /* ---------------------------------------------------------------- */
  const handleCancelInterrupt = useCallback(
    (taskId: string) => {
      updateRun(taskId, { status: 'pending', step: null, interruptData: null, progress: 0 });
      const runId = executionRunRef.current[taskId];
      if (runId) {
        completeExternalExecution({
          runId,
          status: 'cancelled',
          error: 'Interrupted task cancelled by user',
        });
      }
    },
    [completeExternalExecution, updateRun],
  );

  /* ---------------------------------------------------------------- */
  /*  handleClick                                                      */
  /* ---------------------------------------------------------------- */
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
    [executeTask, navigate, runStatesRef, toast],
  );

  return { executeTask, handleResume, handleCancelInterrupt, handleClick };
}
