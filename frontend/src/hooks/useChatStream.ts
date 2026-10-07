import { useCallback } from 'react';
import { v4 as uuidv4 } from 'uuid';

import { apiClient } from '../api/client';
import { StreamRequestError } from '../api/http';
import type { ChatContext, SSECallbacks, SendMessageBody } from '../api/client';
import { useToast } from '../components/ui';
import { useDashboardStore } from '../store/dashboardStore';
import { useExecutionStore } from '../store/executionStore';
import { useStore } from '../store/useStore';
import { ModelSelectionRequiredError } from '../store/modelSelection';
import { zh } from '../locales/zh';
import type { AgentLogSource, ChatRequestSnapshot, Message, ReportIR, ThinkingStep } from '../types';
import { injectChartMarkers, shouldGenerateChart } from '../utils/chartIntent';
import { extractTicker, extractTickers } from '../utils/ticker';

const DEFAULT_HISTORY_LIMIT = Number(import.meta.env.VITE_CHAT_HISTORY_MAX_MESSAGES) || 12;
export const EMPTY_CHAT_RESPONSE_MESSAGE = '模型未返回有效内容，本次分析未完成。请检查模型设置后重试。';

export function hasChatOutput(content: string, report?: Partial<ReportIR> | null): boolean {
  const text = content.trim();
  if (text && text !== '[object Object]') return true;
  return Boolean(report?.summary?.trim() || report?.synthesis_report?.trim() || report?.sections?.length);
}

export interface SendChatStreamOptions {
  outputMode?: 'chat' | 'investment_report';
}

export interface UseChatStreamResult {
  send: (text: string, opts?: SendChatStreamOptions) => Promise<void>;
  retry: (messageId: string) => Promise<void>;
  stop: () => void;
}

interface RunChatStreamOptions extends SendChatStreamOptions {
  retryMessageId?: string;
}

const buildCancelledThinkingStep = (): ThinkingStep => ({
  stage: 'cancelled',
  message: zh.chat.stopped,
  timestamp: new Date().toISOString(),
  eventType: 'trace',
  result: {
    type: 'trace',
    stage: 'cancelled',
    status: 'cancelled',
    summary: zh.chat.stopped,
  },
});

const mapStageToSource = (stage: string): AgentLogSource => {
  const mapping: Record<string, AgentLogSource> = {
    supervisor_start: 'supervisor',
    agent_start: 'planner',
    agent_done: 'planner',
    agent_error: 'planner',
    forum_start: 'forum',
    forum_done: 'forum',
    classifying: 'router',
    classified: 'router',
    agent_selected: 'gate',
    tool_selected: 'gate',
    reasoning: 'supervisor',
    reference_resolution: 'supervisor',
    intent_classification: 'router',
    agent_gate: 'gate',
    data_collection: 'supervisor',
    processing: 'supervisor',
    complete: 'system',
    tool_call: 'system',
    llm_call: 'supervisor',
    error: 'system',
  };
  if (stage === 'understanding' || stage.startsWith('trace_')) return 'router';
  if (stage.startsWith('langgraph_') || stage.startsWith('executor_step') || stage.startsWith('llm_')) return 'supervisor';
  if (stage.startsWith('cache_') || stage === 'api_call' || stage === 'data_source') return 'system';
  if (stage === 'agent_step') return 'planner';
  if (stage.includes('news')) return 'news_agent';
  if (stage.includes('price')) return 'price_agent';
  if (stage.includes('fundamental')) return 'fundamental_agent';
  if (stage.includes('technical')) return 'technical_agent';
  if (stage.includes('macro')) return 'macro_agent';
  if (stage.includes('deep_search') || stage.includes('search')) return 'deep_search_agent';
  return mapping[stage] || 'system';
};

const isFuzzyAnalyzeRequest = (text: string): boolean => {
  const compact = text.replace(/\s+/g, '');
  return [
    /^帮我分析(一下)?(股票|股价|公司|这个|这只|个股)?[？?！!。.]?$/,
    /^分析(一下)?(股票|股价|公司|这个|这只|个股)$/,
    /^(看看|分析下|帮看下)$/,
    /^分析影响[？?！!。.]?$/,
  ].some((pattern) => pattern.test(compact));
};

export const findRetryQuery = (messages: Message[], messageId: string): string | null => {
  const index = messages.findIndex((message) => message.id === messageId);
  if (index < 0) return null;
  const before = [...messages.slice(0, index)].reverse().find((message) => message.role === 'user');
  if (before?.content?.trim()) return before.content.trim();
  const lastUser = [...messages].reverse().find((message) => message.role === 'user');
  return lastUser?.content?.trim() || null;
};

export function useChatStream(sessionId: string): UseChatStreamResult {
  const { toast } = useToast();

  const runChatStream = useCallback(async (rawText: string, opts: RunChatStreamOptions = {}) => {
    const initialState = useStore.getState();
    const requestSessionId = sessionId || initialState.sessionId;
    const retryMessageId = opts.retryMessageId;
    const retryIndex = retryMessageId
      ? initialState.messages.findIndex((message) => message.id === retryMessageId)
      : -1;
    if (retryMessageId && retryIndex < 0) return;
    const retryMessage = retryIndex >= 0 ? initialState.messages[retryIndex] : undefined;
    const previousRequest = retryMessage?.requestSnapshot;
    const userMsgContent = (previousRequest?.query || rawText).trim();
    if (!userMsgContent || initialState.chatLoadingBySession[requestSessionId]) return;

    const guessedTicker = extractTicker(userMsgContent);

    // 1. 模糊查询守卫：重试已有问题时不重复插入澄清消息。
    if (!retryMessageId && isFuzzyAnalyzeRequest(userMsgContent) && !guessedTicker && !initialState.currentTicker) {
      initialState.addMessageToSession(requestSessionId, {
        id: uuidv4(), role: 'user', content: userMsgContent, timestamp: Date.now(),
      });
      initialState.addMessageToSession(requestSessionId, {
        id: uuidv4(),
        role: 'assistant',
        content: zh.chat.clarification,
        timestamp: Date.now(),
      });
      initialState.setDraft('');
      return;
    }

    if (guessedTicker) initialState.setTicker(guessedTicker);
    if (!retryMessageId) initialState.setDraft('');
    const pendingHandoff = retryMessageId ? undefined : initialState.takePendingChatHandoffContext(requestSessionId);

    const isRequestSessionActive = () => useStore.getState().sessionId === requestSessionId;
    const streamController = new AbortController();
    let serverSaved = false;
    const updateScopedMessage = (id: string, patch: Partial<Message>, allowRecovery = false) => {
      useStore.getState().updateMessageInSession(requestSessionId, id, patch, { syncBackend: !serverSaved,
        ...(allowRecovery ? { recovery: { ownerId: initialState.authIdentity?.userId || null,
          runId: requestRunId, userMessageId, controller: streamController, timestamp: requestStartedAt } } : {}),
      });
    };

    // 2. 历史与消息槽位：发送新增消息，重试原位复用 assistant 消息。
    const originalUser = retryMessageId
      ? [...initialState.messages.slice(0, retryIndex)].reverse().find((message) => message.role === 'user'
        && (!retryMessage?.replyTo || message.id === retryMessage.replyTo))
      : undefined;
    const originalUserIndex = originalUser ? initialState.messages.indexOf(originalUser) : retryIndex;
    const historySource = retryIndex >= 0 ? initialState.messages.slice(0, originalUserIndex) : initialState.messages;
    const history = previousRequest?.history ?? historySource
      .filter((message) => message.role === 'user' || message.role === 'assistant')
      .slice(-DEFAULT_HISTORY_LIMIT)
      .map((message) => ({ role: message.role, content: message.content }));

    const requestRunId = uuidv4();
    const userMessageId = originalUser?.id || uuidv4();
    const outputMode = previousRequest?.outputMode ?? opts.outputMode
      ?? (retryMessage?.report ? 'investment_report' : 'chat');
    const context: ChatContext = {};
    if (!retryMessageId) {
      const dashboard = useDashboardStore.getState();
      if (dashboard.activeAsset?.symbol) {
        context.active_symbol = dashboard.activeAsset.symbol;
        context.view = 'chat';
      }
      if (pendingHandoff?.sessionId === requestSessionId) {
        context.source_view = pendingHandoff.sourceView;
        if (pendingHandoff.sourceTab) context.source_tab = pendingHandoff.sourceTab;
      }
      if (dashboard.activeSelections.length === 1) context.selection = dashboard.activeSelections[0];
      if (dashboard.activeSelections.length > 1) context.selections = dashboard.activeSelections;
    }
    // 选区只在首次发送时读取；快照随消息本地保存，重试不受看板切换影响。
    const requestSnapshot: ChatRequestSnapshot = previousRequest ?? {
      query: userMsgContent, outputMode, history,
      context: Object.keys(context).length ? structuredClone(context) : undefined,
    };
    if (!retryMessageId) {
      initialState.addMessageToSession(requestSessionId, {
        id: userMessageId, role: 'user', content: userMsgContent, timestamp: Date.now(),
      });
    }
    let aiMsgId = uuidv4();
    if (retryMessageId) {
      updateScopedMessage(retryMessageId, { id: aiMsgId, runId: requestRunId, replyTo: userMessageId, requestSnapshot,
        content: '', timestamp: Date.now(), isLoading: true, error: undefined, canRetry: false,
        report: undefined, evidence_pool: undefined, thinking: undefined, responseTime: undefined,
        intent: undefined, relatedTicker: undefined, data_origin: undefined, as_of: undefined,
        fallback_used: undefined, tried_sources: undefined });
    } else {
      initialState.addMessageToSession(requestSessionId, {
        id: aiMsgId, runId: requestRunId, replyTo: userMessageId, requestSnapshot,
        role: 'assistant', content: '', timestamp: Date.now(), isLoading: true,
      });
    }

    const store = useStore.getState();
    store.setSessionLoading(requestSessionId, true);
    if (isRequestSessionActive()) store.setStatus(retryMessageId ? zh.chat.retrying : zh.chat.streaming);
    store.setSessionAbortController(requestSessionId, streamController);
    store.addAgentLog({
      id: uuidv4(),
      timestamp: new Date().toISOString(),
      source: 'system',
      level: 'info',
      message: zh.chat.queryLog(Boolean(retryMessageId), `${userMsgContent.slice(0, 50)}${userMsgContent.length > 50 ? '...' : ''}`),
    });
    store.updateAgentStatus('supervisor', { status: 'running', startTime: new Date().toISOString() });

    let fullContent = '';
    let thinkingSteps: ThinkingStep[] = [];
    let execRunId: string | null = null;
    let terminalHandlingPromise: Promise<void> | null = null;
    let terminalClaimed = false;
    let recoveredFromServer = false;
    const recoveryController = new AbortController();
    streamController.signal.addEventListener('abort', () => recoveryController.abort(), { once: true });
    const requestStartedAt = Date.now();
    const confirmAnswerSaved = async (persistenceStatus?: string) => {
      if (persistenceStatus === 'saved' || persistenceStatus === 'ephemeral') return;
      if (isRequestSessionActive()) useStore.getState().setStatus(zh.chat.savingAnswer);
      const saved = persistenceStatus === 'failed' ? false : await useStore.getState().flushConversationSync(requestSessionId);
      if (!saved && isRequestSessionActive()) {
        toast({ type: 'warning', title: zh.chat.answerSaveFailedTitle, message: zh.chat.answerSaveFailedMessage });
      }
    };

    const finishAbortedStream = () => {
      if (!thinkingSteps.some((step) => step.stage === 'cancelled')) {
        thinkingSteps = [...thinkingSteps, buildCancelledThinkingStep()];
      }
      updateScopedMessage(aiMsgId, {
        content: fullContent || zh.chat.stopped,
        isLoading: false,
        thinking: thinkingSteps,
      });
      const current = useStore.getState();
      if (isRequestSessionActive() && (!current.abortControllersBySession[requestSessionId]
        || current.abortControllersBySession[requestSessionId] === streamController)) current.setStatus(zh.chat.stopped);
      current.addAgentLog({
        id: uuidv4(), timestamp: new Date().toISOString(), source: 'system', level: 'warn', message: zh.chat.stopped,
      });
      current.updateAgentStatus('supervisor', {
        status: 'waiting', endTime: new Date().toISOString(), lastMessage: zh.chat.stopped,
      });
      if (execRunId) useExecutionStore.getState().completeExternalExecution({ runId: execRunId, status: 'cancelled' });
    };

    try {
      // 4. 所有发送/重试共用同一个 SSE 管线。
      const request: SendMessageBody = {
          query: userMsgContent,
          run_id: requestRunId,
          client_user_message_id: userMessageId,
          client_assistant_message_id: aiMsgId,
          history,
          context: requestSnapshot.context,
          options: {
            output_mode: outputMode,
            ...(outputMode === 'investment_report' ? { strict_selection: false } : {}),
            trace_raw_override: initialState.traceRawEnabled ? 'on' : 'off',
          },
          session_id: requestSessionId || undefined,
        };
      const ownsRequest = () => {
        const current = useStore.getState();
        return !streamController.signal.aborted && !recoveryController.signal.aborted
          && (current.authIdentity?.userId || null) === (initialState.authIdentity?.userId || null)
          && current.abortControllersBySession[requestSessionId] === streamController
          && current.chatLoadingBySession[requestSessionId];
      };
      let pendingRecovery: Promise<boolean> | null = null;
      const recoverDelivery = (): Promise<boolean> => {
        if (pendingRecovery) return pendingRecovery;
        pendingRecovery = (async () => {
          if (!ownsRequest() || terminalClaimed || !initialState.authIdentity) return false;
          try {
            const run = await apiClient.getExecutionRun(execRunId || requestRunId, recoveryController.signal);
            if (!ownsRequest() || terminalClaimed || run.run_id !== (execRunId || requestRunId)
              || run.session_id !== requestSessionId || run.user_message_id !== userMessageId
              || run.status !== 'completed' || run.result?.type !== 'done') return false;
            const result = run.result;
            const content = result.assistant_message?.content || result.response || '';
            if (typeof content !== 'string' || !hasChatOutput(content, result.report || result.blocked_report)) return false;
            recoveredFromServer = true;
            callbacks.onDone?.(result.report, result.thinking, result);
            const completion = terminalHandlingPromise;
            if (completion) await completion;
            streamController.abort();
            return true;
          } catch {
            return false;
          } finally {
            pendingRecovery = null;
          }
        })();
        return pendingRecovery;
      };
      let polling = false;
      const startDeliveryRecovery = () => {
        if (polling || terminalClaimed || !initialState.authIdentity) return;
        polling = true;
        void (async () => {
          while (ownsRequest() && !terminalClaimed) {
            if (await recoverDelivery()) break;
            await new Promise<void>((resolve) => {
              const stop = () => { clearTimeout(timer); resolve(); };
              const timer = setTimeout(() => { recoveryController.signal.removeEventListener('abort', stop); resolve(); }, 1500);
              if (recoveryController.signal.aborted) stop();
              else recoveryController.signal.addEventListener('abort', stop, { once: true });
            });
          }
        })();
      };
      const callbacks: SSECallbacks = {
          onToken: (token) => {
            if (terminalClaimed) return;
            const safeToken = typeof token === 'string' ? token : JSON.stringify(token);
            if (safeToken) {
              fullContent += safeToken;
              if (execRunId) useExecutionStore.getState().ingestExternalToken(execRunId, safeToken);
            }
            updateScopedMessage(aiMsgId, { content: fullContent, isLoading: true }, true);
          },
          onToolStart: (name) => {
            const current = useStore.getState();
            if (isRequestSessionActive()) current.setStatus(zh.chat.callingTool(name));
            current.addAgentLog({
              id: uuidv4(), timestamp: new Date().toISOString(), source: 'system', level: 'info',
              message: zh.chat.toolStarted(name), tool_name: name,
            });
          },
          onToolEnd: () => {
            const current = useStore.getState();
            if (isRequestSessionActive()) current.setStatus(zh.chat.generatingResponse);
            current.addAgentLog({
              id: uuidv4(), timestamp: new Date().toISOString(), source: 'system', level: 'success',
              message: zh.chat.toolCompleted,
            });
          },
          onDone: (report, thinking, meta) => {
            if (terminalClaimed) return;
            terminalClaimed = true;
            terminalHandlingPromise = (async () => {
              const degraded = meta?.degraded === true;
              serverSaved = meta?.persistence_status === 'saved';
              if (typeof meta?.assistant_message?.content === 'string') fullContent = meta.assistant_message.content;
              const doneStep: ThinkingStep = {
                stage: 'done',
                message: meta?.quality_blocked ? zh.chat.qualityBlocked
                  : meta?.answer_status === 'partial' ? zh.chat.analysisPartial : zh.chat.analysisDone,
                timestamp: new Date().toISOString(),
                eventType: 'done',
                result: { type: 'done', status: 'done', reason: meta?.reason },
              };
              thinkingSteps = [...thinkingSteps, doneStep];
              const metrics = meta?.metrics || {};
              if (metrics && typeof metrics === 'object') {
                useStore.getState().setRequestMetrics({
                  llmTotalCalls: Number(metrics.llm_total_calls || 0),
                  toolTotalCalls: Number(metrics.tool_total_calls || 0),
                  updatedAt: new Date().toISOString(),
                });
              }
              if (thinking?.length) {
                const existing = new Set(thinkingSteps.map((step) => `${step.stage}-${step.message}`));
                const additions = thinking.filter((step) => !existing.has(`${step.stage}-${step.message}`));
                if (additions.length > 0 && thinkingSteps.length > 0) thinkingSteps = [...thinkingSteps, ...additions];
                else if (thinking.length >= thinkingSteps.length) thinkingSteps = thinking;
              }
              if (!fullContent || fullContent.trim() === '' || fullContent.trim() === '[object Object]') {
                const blockedReport = meta?.blocked_report && typeof meta.blocked_report === 'object' ? meta.blocked_report : null;
                const fallback = typeof meta?.response === 'string' && meta.response.trim()
                  ? meta.response
                  : report?.summary || blockedReport?.summary || '';
                if (fallback) fullContent = fallback;
              }
              if (!report && meta?.blocked_report && typeof meta.blocked_report === 'object') report = meta.blocked_report;
              if (!hasChatOutput(fullContent, report)) {
                thinkingSteps = [...thinkingSteps.filter((step) => step.stage !== 'done'), {
                  stage: 'error', message: EMPTY_CHAT_RESPONSE_MESSAGE, timestamp: new Date().toISOString(),
                  eventType: 'error', result: { type: 'error', status: 'error', code: 'empty_model_response' },
                }];
                updateScopedMessage(aiMsgId, { content: EMPTY_CHAT_RESPONSE_MESSAGE, isLoading: false,
                  error: EMPTY_CHAT_RESPONSE_MESSAGE, canRetry: true, thinking: thinkingSteps });
                const current = useStore.getState();
                current.addAgentLog({ id: uuidv4(), timestamp: new Date().toISOString(), source: 'system', level: 'error', message: EMPTY_CHAT_RESPONSE_MESSAGE });
                current.updateAgentStatus('supervisor', { status: 'error', lastMessage: EMPTY_CHAT_RESPONSE_MESSAGE });
                if (execRunId) useExecutionStore.getState().completeExternalExecution({ runId: execRunId, status: 'error', error: EMPTY_CHAT_RESPONSE_MESSAGE });
                if (isRequestSessionActive()) current.setStatus(null);
                toast({ type: 'error', title: zh.chat.requestFailed, message: EMPTY_CHAT_RESPONSE_MESSAGE });
                return;
              }
              const nextFocus = meta?.current_focus || report?.ticker || guessedTicker || null;
              if (nextFocus) useStore.getState().setTicker(nextFocus);
              const canonicalId = typeof meta?.assistant_message?.id === 'string' ? meta.assistant_message.id : aiMsgId;
              updateScopedMessage(aiMsgId, {
                id: canonicalId,
                content: fullContent,
                isLoading: false,
                report,
                thinking: thinkingSteps,
                evidence_pool: meta?.evidence_pool ?? meta?.data?.evidence_pool,
                fallback_used: degraded,
                data_origin: degraded ? 'LLM' : undefined,
                canRetry: meta?.quality_blocked === true || meta?.persistence_status === 'failed',
              }, true);
              aiMsgId = canonicalId;
              await confirmAnswerSaved(meta?.persistence_status);
              if (degraded) {
                toast({ type: 'warning', title: zh.chat.degradedTitle, message: typeof meta?.degradation_message === 'string' && meta.degradation_message.trim()
                  ? meta.degradation_message : zh.chat.degradedMessage });
              }

              // 5. 文本先落定，图表异步补挂。
              void (async () => {
                let patched = fullContent;
                try {
                  const chartInfo = await shouldGenerateChart(userMsgContent, nextFocus || initialState.currentTicker || null);
                  const tickers = chartInfo.tickers.length ? chartInfo.tickers : extractTickers(userMsgContent);
                  const forceMulti = tickers.length > 1;
                  if (chartInfo.chartType || forceMulti) {
                    const withMarkers = injectChartMarkers(patched, tickers, chartInfo.chartType, {
                      valueMode: chartInfo.valueMode,
                      period: chartInfo.period,
                    });
                    if (withMarkers !== patched && tickers.length === 1) useStore.getState().setTicker(tickers[0]);
                    patched = withMarkers;
                  }
                  if (patched !== fullContent) updateScopedMessage(aiMsgId, { content: patched });
                } catch (error) {
                  console.warn('chart enrichment skipped:', error);
                }
            })();

            if (execRunId) {
              useExecutionStore.getState().completeExternalExecution({ runId: execRunId, status: 'done', report: report ?? null, meta });
            }
            if (isRequestSessionActive()) useStore.getState().setStatus(null);
            })();
          },
          onError: (error) => {
            if (terminalClaimed) return;
            terminalHandlingPromise = (async () => {
              if (await recoverDelivery() || terminalClaimed) return;
              updateScopedMessage(aiMsgId, {
                content: fullContent || zh.chat.streamInterrupted,
                isLoading: false,
                error: String(error),
                canRetry: true,
              });
              const current = useStore.getState();
              if (isRequestSessionActive()) current.setStatus(zh.chat.streamInterrupted);
              toast({ type: 'error', title: zh.chat.streamInterruptedTitle, message: zh.chat.streamInterruptedMessage });
              current.addAgentLog({
                id: uuidv4(), timestamp: new Date().toISOString(), source: 'system', level: 'error', message: zh.chat.errorPrefix(String(error)),
              });
              current.updateAgentStatus('supervisor', { status: 'error', lastMessage: error });
              if (execRunId) useExecutionStore.getState().completeExternalExecution({ runId: execRunId, status: 'error', error: String(error) });
            })();
          },
          onThinking: (step) => {
            if (terminalClaimed) return;
            const stepRunId = (typeof step.runId === 'string' && step.runId)
              || (step.result && typeof (step.result as Record<string, unknown>).run_id === 'string'
                ? (step.result as Record<string, string>).run_id
                : null);
            if (stepRunId) {
              const execution = useExecutionStore.getState();
              if (execRunId !== stepRunId) {
                execRunId = stepRunId;
                execution.beginExternalExecution({
                  runId: stepRunId,
                  query: userMsgContent,
                  tickers: extractTickers(userMsgContent),
                  source: 'chat',
                  outputMode,
                });
              }
              // 6. 进度只由 executionStore reducer 推导，不再维护 ChatInput 本地百分比表。
              execution.ingestExternalThinking(stepRunId, step);
            }
            if (step.eventType === 'pipeline_stage' && step.result?.stage === 'done') startDeliveryRecovery();
            thinkingSteps = [...thinkingSteps, step];
            updateScopedMessage(aiMsgId, { thinking: thinkingSteps });
            const source = mapStageToSource(step.stage);
            const isError = step.stage.includes('error');
            const isComplete = step.stage.includes('done') || step.stage.includes('complete');
            const isStart = step.stage.includes('start');
            const current = useStore.getState();
            current.addAgentLog({
              id: uuidv4(), timestamp: step.timestamp || new Date().toISOString(), source,
              level: isError ? 'error' : isComplete ? 'success' : 'info',
              message: step.message || step.stage, details: step.result,
            });
            if (isStart) current.updateAgentStatus(source, { status: 'running', startTime: step.timestamp || new Date().toISOString(), lastMessage: step.message });
            else if (isComplete) current.updateAgentStatus(source, { status: 'success', endTime: step.timestamp || new Date().toISOString(), lastMessage: step.message });
            else if (isError) current.updateAgentStatus(source, { status: 'error', endTime: step.timestamp || new Date().toISOString(), lastMessage: step.message });
          },
          onRawEvent: (event) => useStore.getState().addRawEvent(event),
        };
      await apiClient.sendMessageStream(request, callbacks, {
          traceRawEnabled: initialState.traceRawEnabled,
          signal: streamController.signal,
          shouldCancelRunOnAbort: () => !recoveredFromServer,
          onConnectionState: (state) => {
            if (terminalClaimed || !isRequestSessionActive()) return;
            const current = useStore.getState();
            if (state === 'reconnecting') current.setStatus(zh.chat.reconnecting);
            else if (state === 'connected') current.setStatus(zh.chat.streaming);
            else current.setStatus(zh.chat.streamInterrupted);
          },
        });
      const pendingTerminalHandling = terminalHandlingPromise;
      if (pendingTerminalHandling) await pendingTerminalHandling;
      if (streamController.signal.aborted && !recoveredFromServer) finishAbortedStream();
    } catch (error) {
      if (streamController.signal.aborted && recoveredFromServer) return;
      if (streamController.signal.aborted) {
        finishAbortedStream();
        return;
      }
      const message = error instanceof StreamRequestError || error instanceof ModelSelectionRequiredError
        ? error.message : zh.chat.networkRequestFailed;
      updateScopedMessage(aiMsgId, { content: message, isLoading: false, error: message, canRetry: true });
      const current = useStore.getState();
      if (isRequestSessionActive()) current.setStatus(zh.chat.requestFailed);
      toast({ type: 'error', title: zh.chat.requestFailed, message });
      current.addAgentLog({
        id: uuidv4(), timestamp: new Date().toISOString(), source: 'system', level: 'error',
        message: error instanceof Error ? error.message : zh.chat.networkRequestFailed,
      });
    } finally {
      terminalClaimed = true;
      recoveryController.abort();
      // 7. 会话级 loading/AbortController 收尾；executionStore 保持唯一进度真相源。
      const current = useStore.getState();
      if (current.abortControllersBySession[requestSessionId] === streamController) {
        current.setSessionLoading(requestSessionId, false);
        if (isRequestSessionActive()) {
          if (streamController.signal.aborted && !recoveredFromServer) current.setStatus(zh.chat.stopped);
          else current.setStatus(null);
          current.resetExecutionState();
        }
        current.setSessionAbortController(requestSessionId, null);
      }
    }
  }, [sessionId, toast]);

  const send = useCallback((text: string, opts?: SendChatStreamOptions) => (
    runChatStream(text, opts)
  ), [runChatStream]);

  const retry = useCallback(async (messageId: string) => {
    const state = useStore.getState();
    if (state.isChatLoading) return;
    const query = findRetryQuery(state.messages, messageId);
    if (!query) {
      state.setStatus(zh.chat.noRetryQuery);
      setTimeout(() => {
        if (useStore.getState().sessionId === sessionId) useStore.getState().setStatus(null);
      }, 1500);
      return;
    }
    await runChatStream(query, { retryMessageId: messageId });
  }, [runChatStream, sessionId]);

  const stop = useCallback(() => useStore.getState().cancelChatStream(), []);

  return { send, retry, stop };
}
