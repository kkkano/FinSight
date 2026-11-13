import { useCallback } from 'react';
import { v4 as uuidv4 } from 'uuid';

import { apiClient } from '../api/client';
import { StreamRequestError } from '../api/http';
import type { ChatContext, SSECallbacks, SendMessageBody } from '../api/client';
import { useToast } from '../components/ui';
import { useDashboardStore } from '../store/dashboardStore';
import { useStore } from '../store/useStore';
import { ModelSelectionRequiredError } from '../store/modelSelection';
import { zh } from '../locales/zh';
import type { AgentLogSource, ChatRequestSnapshot, Message, ReportIR, ThinkingStep } from '../types';
import type { ChatImageInput, ReviewRevisionRequest } from '../types/runtime';
import { injectChartMarkers, shouldGenerateChart } from '../utils/chartIntent';
import { extractTicker, extractTickers } from '../utils/ticker';
import { hasUnselectedSkillCommand, MAX_SELECTED_SKILLS } from '../utils/skillCommands';
import { answerForReview, applyResearchEvent, emptyResearchStream, publicResearchBlocks, researchFailureMessage, researchQualityMessage, researchText, useRuntimeMemory } from '../store/researchStream';

const DEFAULT_HISTORY_LIMIT = Number(import.meta.env.VITE_CHAT_HISTORY_MAX_MESSAGES) || 12;
export const EMPTY_CHAT_RESPONSE_MESSAGE = '模型没有返回有效内容。请检查模型设置后重试。';

export function hasChatOutput(content: string, report?: Partial<ReportIR> | null): boolean {
  const text = content.trim();
  if (text && text !== '[object Object]') return true;
  return Boolean(report?.summary?.trim() || report?.synthesis_report?.trim() || report?.sections?.length);
}

export interface SendChatStreamOptions {
  skillIds?: string[];
  images?: ChatImageInput[];
  outputMode?: 'chat' | 'investment_report';
}

export interface UseChatStreamResult {
  send: (text: string, opts?: SendChatStreamOptions) => Promise<void>;
  retry: (messageId: string) => Promise<void>;
  revise: (messageId: string, reviewId: string) => Promise<void>;
  stop: () => void;
  steer: (text: string) => Promise<boolean>;
}

interface RunChatStreamOptions extends SendChatStreamOptions {
  retryMessageId?: string;
  reviewRevision?: ReviewRevisionRequest;
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
    if (retryMessageId && previousRequest?.hasTransientImages) {
      initialState.setDraft(previousRequest.query);
      toast({ type: 'warning', title: '请重新附图', message: '图片仅用于原轮研究，不保存在历史中。重新选择 PNG 后发送。' });
      return;
    }
    const requestImages = !retryMessageId && opts.images?.length
      ? opts.images.map(({ data_url, name }) => ({ data_url, ...(name ? { name } : {}) })) : undefined;
    const userMsgContent = (previousRequest?.query || rawText).trim();
    if (!userMsgContent || initialState.chatLoadingBySession[requestSessionId]) return;
    if (hasUnselectedSkillCommand(userMsgContent)) {
      toast({ type: 'warning', title: '请选择研究技能', message: '先从 / 菜单选择技能，再输入研究问题。' });
      return;
    }

    const reviewRevision = previousRequest?.reviewRevision ?? opts.reviewRevision;
    const guessedTicker = reviewRevision ? null : extractTicker(userMsgContent);

    // 1. 模糊查询守卫：重试已有问题时不重复插入澄清消息。
    if (!reviewRevision && !retryMessageId && !requestImages?.length && isFuzzyAnalyzeRequest(userMsgContent) && !guessedTicker && !initialState.currentTicker) {
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
    const pendingHandoff = retryMessageId || reviewRevision ? undefined : initialState.takePendingChatHandoffContext(requestSessionId);
    const resumeFromRunId = reviewRevision?.source_run_id ?? (retryMessageId && retryMessage?.runId && !retryMessage.isLoading
      && (retryMessage.error || ['failed', 'interrupted', 'persistence_failed', 'cancelled'].includes(retryMessage.runStatus || ''))
      ? retryMessage.runId : undefined);

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
    if (!retryMessageId && !reviewRevision) {
      const dashboard = useDashboardStore.getState();
      if (dashboard.activeAsset?.symbol) {
        context.active_symbol = dashboard.activeAsset.symbol;
        context.view = 'chat';
      }
      if (pendingHandoff?.sessionId === requestSessionId) {
        context.source_view = pendingHandoff.sourceView;
        if (pendingHandoff.sourceTab) context.source_tab = pendingHandoff.sourceTab;
        if (pendingHandoff.selectedMetric) context.selected_metric = pendingHandoff.selectedMetric;
        if (pendingHandoff.timeRange) context.time_range = pendingHandoff.timeRange;
        if (pendingHandoff.dataRefs?.length) context.data_refs = pendingHandoff.dataRefs;
      }
      if (dashboard.activeSelections.length === 1) context.selection = dashboard.activeSelections[0];
      if (dashboard.activeSelections.length > 1) context.selections = dashboard.activeSelections;
    }
    // 选区只在首次发送时读取；快照随消息本地保存，重试不受看板切换影响。
    const requestSnapshot: ChatRequestSnapshot = previousRequest ? { ...previousRequest, resumeFromRunId } : {
      query: userMsgContent, outputMode, history, resumeFromRunId,
      ...(reviewRevision ? { reviewRevision: structuredClone(reviewRevision) } : {}),
      ...(opts.skillIds?.length ? { skillIds: [...new Set(opts.skillIds)].slice(0, MAX_SELECTED_SKILLS) } : {}),
      ...(requestImages?.length ? { hasTransientImages: true } : {}),
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
        report: undefined, evidence_pool: undefined, thinking: undefined, blocks: undefined, runStatus: 'running', answerStatus: 'streaming', responseTime: undefined,
        intent: undefined, relatedTicker: undefined, data_origin: undefined, as_of: undefined,
        fallback_used: undefined, tried_sources: undefined });
    } else {
      initialState.addMessageToSession(requestSessionId, {
        id: aiMsgId, runId: requestRunId, replyTo: userMessageId, requestSnapshot,
        ...(reviewRevision ? { reviewRevision: structuredClone(reviewRevision) } : {}),
        role: 'assistant', content: '', timestamp: Date.now(), isLoading: true, runStatus: 'running', answerStatus: 'streaming',
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
    let runtimeState = emptyResearchStream(requestRunId);
    let runtimeTextStarted = false;
    let answerCompleted = false;
    let contentFlushTimer: ReturnType<typeof setTimeout> | null = null;
    const scheduleContentUpdate = () => {
      if (contentFlushTimer) return;
      contentFlushTimer = setTimeout(() => {
        contentFlushTimer = null;
        if (!terminalClaimed) updateScopedMessage(aiMsgId, { content: fullContent, blocks: runtimeState.blocks, isLoading: !answerCompleted }, true);
      }, 40);
    };
    useRuntimeMemory.getState().beginOwner(initialState.authIdentity?.userId || null);
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
        thinking: thinkingSteps, blocks: runtimeState.blocks, runStatus: 'cancelled', answerStatus: 'partial',
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
    };

    try {
      // 4. 所有发送/重试共用同一个 SSE 管线。
      const request: SendMessageBody = {
          query: userMsgContent,
          ...(requestSnapshot.reviewRevision ? { review_revision: requestSnapshot.reviewRevision } : {}),
          ...(requestSnapshot.skillIds?.length ? { skill_ids: requestSnapshot.skillIds } : {}),
          ...(requestImages?.length ? { images: requestImages } : {}),
          show_provider_reasoning: initialState.showProviderReasoning === true,
          ...(requestSnapshot.resumeFromRunId ? { resume_from_run_id: requestSnapshot.resumeFromRunId } : {}),
          run_id: requestRunId,
          client_user_message_id: userMessageId,
          client_assistant_message_id: aiMsgId,
          history,
          context: { ...requestSnapshot.context, show_provider_reasoning: initialState.showProviderReasoning === true,
            watchlist_auto_confirm: initialState.watchlistAutoConfirm === true },
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
              || !['completed', 'persistence_failed', 'failed', 'cancelled', 'interrupted'].includes(run.status)
              || !run.result || !['done', 'error', 'cancelled'].includes(String(run.result.type))) return false;
            const result: Record<string, any> = { ...run.result, run_status: run.result.run_status || run.status };
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
          onRuntimeEvent: (event) => {
            if (terminalClaimed || (event.run_id && event.run_id !== requestRunId)
              || (event.session_id && event.session_id !== requestSessionId)
              || (useStore.getState().authIdentity?.userId || null) !== (initialState.authIdentity?.userId || null)) return;
            const next = applyResearchEvent(runtimeState, event);
            if (next === runtimeState) return;
            runtimeState = next;
            if (event.type === 'answer.completed') {
              answerCompleted = true;
              if (contentFlushTimer) clearTimeout(contentFlushTimer);
              contentFlushTimer = null;
              updateScopedMessage(aiMsgId, { content: fullContent, blocks: runtimeState.blocks,
                isLoading: false, answerStatus: 'complete' }, true);
            }
            if (event.type.startsWith('content.') || event.type === 'snapshot.reset') {
              runtimeTextStarted = true;
              fullContent = researchText(runtimeState.blocks);
            }
            if (event.type.startsWith('content.') || event.type.startsWith('artifact.')
              || event.type.startsWith('reasoning.') || event.type.startsWith('action.')
              || event.type.startsWith('review.') || event.type === 'snapshot.reset') {
              scheduleContentUpdate();
            }
          },
          onToken: (token) => {
            if (terminalClaimed || runtimeTextStarted) return;
            const safeToken = typeof token === 'string' ? token : JSON.stringify(token);
            if (safeToken) {
              fullContent += safeToken;
            }
            scheduleContentUpdate();
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
              const saveFailed = meta?.persistence_status === 'failed' || meta?.run_status === 'persistence_failed';
              const cancelled = meta?.run_status === 'cancelled';
              const deliveryFailed = !cancelled && (saveFailed || meta?.success === false || ['failed', 'interrupted'].includes(meta?.run_status));
              const partial = deliveryFailed || meta?.answer_status === 'partial' || meta?.quality_blocked === true;
              const failureMessage = saveFailed ? '回答已生成，但未保存成功。' : researchFailureMessage(meta);
              const qualityMessage = researchQualityMessage(meta);
              serverSaved = meta?.persistence_status === 'saved';
              if (typeof meta?.assistant_message?.content === 'string') fullContent = meta.assistant_message.content;
              else if (typeof meta?.response === 'string' && meta.response.trim()) fullContent = meta.response;
              const doneStep: ThinkingStep = {
                stage: cancelled ? 'cancelled' : deliveryFailed ? 'error' : 'done',
                message: cancelled ? zh.chat.stopped : deliveryFailed ? failureMessage : partial ? qualityMessage : zh.chat.analysisDone,
                timestamp: new Date().toISOString(),
                eventType: 'done',
                result: { type: 'done', status: cancelled ? 'cancelled' : deliveryFailed ? 'error' : partial ? 'partial' : 'done',
                  reason: deliveryFailed ? failureMessage : partial ? qualityMessage : undefined,
                  error_code: meta?.error_code, recovery_action: meta?.recovery_action },
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
              // 未保存或未通过发布门禁的内容保留为正文/产物，不能生成已归档报告链接。
              if (saveFailed || meta?.publishable === false || meta?.quality_blocked === true) report = undefined;
              if (deliveryFailed && !hasChatOutput(fullContent, report)) fullContent = failureMessage;
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
                if (isRequestSessionActive()) current.setStatus(null);
                toast({ type: 'error', title: zh.chat.requestFailed, message: EMPTY_CHAT_RESPONSE_MESSAGE });
                return;
              }
              const nextFocus = meta?.current_focus || report?.ticker || guessedTicker || null;
              if (nextFocus && isRequestSessionActive()) useStore.getState().setTicker(nextFocus);
              const canonicalId = typeof meta?.assistant_message?.id === 'string' ? meta.assistant_message.id : aiMsgId;
              updateScopedMessage(aiMsgId, {
                id: canonicalId,
                content: fullContent,
                isLoading: false,
                runStatus: saveFailed ? 'persistence_failed' : meta?.run_status || (partial ? 'partial' : 'completed'),
                error: deliveryFailed ? failureMessage : undefined,
                answerStatus: meta?.answer_status || (partial || cancelled ? 'partial' : 'complete'),
                blocks: publicResearchBlocks(meta?.assistant_message?.blocks ?? meta?.blocks ?? runtimeState.blocks),
                reviewRevision: meta?.assistant_message?.review_revision ?? meta?.review_revision ?? requestSnapshot.reviewRevision,
                report,
                thinking: thinkingSteps,
                evidence_pool: meta?.evidence_pool ?? meta?.data?.evidence_pool,
                priceLevels: meta?.assistant_message?.price_levels ?? meta?.price_levels,
                fallback_used: degraded,
                data_origin: degraded ? 'LLM' : undefined,
                canRetry: partial,
              }, true);
              aiMsgId = canonicalId;
              await confirmAnswerSaved(meta?.persistence_status);
              if (degraded) {
                toast({ type: 'warning', title: zh.chat.degradedTitle, message: typeof meta?.degradation_message === 'string' && meta.degradation_message.trim()
                  ? meta.degradation_message : zh.chat.degradedMessage });
              }

              // 5. 文本先落定，图表异步补挂。
              if (!runtimeTextStarted && !Array.isArray(meta?.assistant_message?.blocks ?? meta?.blocks)
                  && !deliveryFailed && !cancelled) void (async () => {
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
                    if (withMarkers !== patched && tickers.length === 1 && isRequestSessionActive()) useStore.getState().setTicker(tickers[0]);
                    patched = withMarkers;
                  }
                  if (patched !== fullContent) updateScopedMessage(aiMsgId, { content: patched });
                } catch (error) {
                  console.warn('chart enrichment skipped:', error);
                }
            })();

            if (isRequestSessionActive()) useStore.getState().setStatus(null);
            })();
          },
          onError: (error, meta) => {
            if (terminalClaimed) return;
            if (typeof meta?.response === 'string' && meta.response.trim()) fullContent = meta.response;
            if (Array.isArray(meta?.blocks)) runtimeState = { ...runtimeState, blocks: publicResearchBlocks(meta.blocks) };
            terminalHandlingPromise = (async () => {
              if (await recoverDelivery() || terminalClaimed) return;
              terminalClaimed = true;
              const failureMessage = researchFailureMessage(meta);
              serverSaved = meta?.persistence_status === 'saved';
              thinkingSteps = [...thinkingSteps, { stage: 'error', eventType: 'error', message: failureMessage,
                timestamp: new Date().toISOString(), result: { status: 'error', error_code: meta?.error_code,
                  reason: meta?.reason, failure_detail: String(error), recovery_action: meta?.recovery_action } }];
              updateScopedMessage(aiMsgId, {
                content: fullContent || failureMessage,
                isLoading: false,
                error: failureMessage, runStatus: String(meta?.run_status || 'failed'), answerStatus: fullContent ? 'partial' : 'unavailable', blocks: runtimeState.blocks,
                thinking: thinkingSteps,
                canRetry: true,
              }, true);
              const current = useStore.getState();
              if (isRequestSessionActive()) current.setStatus(zh.chat.streamInterrupted);
              toast({ type: 'error', title: zh.chat.streamInterruptedTitle, message: failureMessage });
              current.addAgentLog({
                id: uuidv4(), timestamp: new Date().toISOString(), source: 'system', level: 'error', message: zh.chat.errorPrefix(failureMessage),
              });
              current.updateAgentStatus('supervisor', { status: 'error', lastMessage: failureMessage });
            })();
          },
          onThinking: (step) => {
            if (terminalClaimed) return;
            const stepRunId = (typeof step.runId === 'string' && step.runId)
              || (step.result && typeof (step.result as Record<string, unknown>).run_id === 'string'
                ? (step.result as Record<string, string>).run_id
                : null);
            if (stepRunId) execRunId = stepRunId;
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
      const failure = error instanceof ModelSelectionRequiredError ? {error_code:'model_selection_required'} : error;
      const message = researchFailureMessage(failure, zh.chat.networkRequestFailed);
      thinkingSteps = [...thinkingSteps, { stage: 'error', eventType: 'error', message, timestamp: new Date().toISOString(),
        result: {error_code:error instanceof StreamRequestError ? error.code : error instanceof ModelSelectionRequiredError ? 'model_selection_required' : undefined,
          failure_detail:error instanceof Error ? error.message : String(error)} }];
      updateScopedMessage(aiMsgId, { content: fullContent || message, isLoading: false, error: message, canRetry: true,
        runStatus: 'failed', answerStatus: fullContent ? 'partial' : 'unavailable', thinking: thinkingSteps, blocks: runtimeState.blocks }, true);
      const current = useStore.getState();
      if (isRequestSessionActive()) current.setStatus(zh.chat.requestFailed);
      toast({ type: 'error', title: zh.chat.requestFailed, message });
      current.addAgentLog({
        id: uuidv4(), timestamp: new Date().toISOString(), source: 'system', level: 'error',
        message: error instanceof Error ? error.message : zh.chat.networkRequestFailed,
      });
    } finally {
      if (contentFlushTimer) clearTimeout(contentFlushTimer);
      terminalClaimed = true;
      recoveryController.abort();
      // 7. 保留会话级 loading/AbortController 收尾。
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

  const revise = useCallback(async (messageId: string, reviewId: string) => {
    const state = useStore.getState();
    if (state.sessionId !== sessionId || state.chatLoadingBySession[sessionId]) return;
    const message = state.messages.find((item) => item.id === messageId && item.role === 'assistant');
    const block = message?.blocks?.find((item) => item.kind === 'review' && item.review.review_id === reviewId);
    if (!message?.runId || message.isLoading || block?.kind !== 'review' || block.review.status !== 'completed') return;
    const review = block.review;
    await runChatStream(zh.chat.review.revise, {
      outputMode: message.requestSnapshot?.outputMode ?? (message.report ? 'investment_report' : 'chat'),
      reviewRevision: { source_message_id: message.id, source_run_id: message.runId, review_id: review.review_id,
        answer: answerForReview(message.blocks ?? [], reviewId, message.content),
        findings: review.findings ?? [], coverage: review.coverage ?? [] },
    });
  }, [runChatStream, sessionId]);

  const steer = useCallback(async (text: string): Promise<boolean> => {
    const state = useStore.getState();
    const scopedMessages = state.sessionId === sessionId ? state.messages : [];
    const active = [...scopedMessages].reverse().find((message) => message.role === 'assistant' && message.isLoading && message.runId);
    if (!active?.runId || !text.trim()) return false;
    const owner = state.authIdentity?.userId;
    try {
      const receipt = await apiClient.sendRunInstruction(active.runId, text.trim(), uuidv4());
      if (useStore.getState().sessionId !== sessionId || useStore.getState().authIdentity?.userId !== owner) return false;
      if (!['accepted', 'queued', 'delivered'].includes(receipt.status)) throw new Error('研究已经结束，请重新发送这条消息。');
      state.setDraft('');
      toast({ type: 'success', title: '已收到补充要求', message: '会继续按你的要求研究。' });
      return true;
    } catch (error) {
      toast({ type: 'error', title: '补充要求未发送', message: error instanceof Error ? error.message : '请稍后重试' });
      return false;
    }
  }, [sessionId, toast]);

  return { send, retry, revise, stop, steer };
}
