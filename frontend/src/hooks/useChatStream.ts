import { useCallback } from 'react';
import { v4 as uuidv4 } from 'uuid';

import { apiClient } from '../api/client';
import type { ChatContext } from '../api/client';
import type { PortfolioSummaryPosition } from '../api/contracts';
import { getAgentPreferences } from '../components/settings/AgentControlPanel';
import { useToast } from '../components/ui';
import { queryClient } from '../queryClient';
import { useDashboardStore } from '../store/dashboardStore';
import { useExecutionStore } from '../store/executionStore';
import { useStore } from '../store/useStore';
import { zh } from '../locales/zh';
import type { AgentLogSource, Message, ThinkingStep } from '../types';
import { injectChartMarkers, shouldGenerateChart } from '../utils/chartIntent';
import { extractTicker, extractTickers } from '../utils/ticker';
import { parseAgentMentions } from './useAgentMention';

const DEFAULT_HISTORY_LIMIT = Number(import.meta.env.VITE_CHAT_HISTORY_MAX_MESSAGES) || 12;

export interface SendChatStreamOptions {
  agentsOverride?: string[];
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

export const normalizePortfolioPositionsForChat = (
  positions: PortfolioSummaryPosition[] | null | undefined,
): PortfolioSummaryPosition[] => (Array.isArray(positions) ? positions : [])
  .filter((position) => {
    const ticker = String(position?.ticker || '').trim();
    const shares = Number(position?.shares);
    return Boolean(ticker) && Number.isFinite(shares) && shares > 0;
  })
  .map((position) => ({
    ...position,
    ticker: position.ticker.trim().toUpperCase(),
    shares: Number(position.shares),
  }));

export function useChatStream(sessionId: string): UseChatStreamResult {
  const { toast } = useToast();

  const runChatStream = useCallback(async (rawText: string, opts: RunChatStreamOptions = {}) => {
    const userMsgContent = rawText.trim();
    const initialState = useStore.getState();
    const requestSessionId = sessionId || initialState.sessionId;
    if (!userMsgContent || initialState.chatLoadingBySession[requestSessionId]) return;

    const retryMessageId = opts.retryMessageId;
    const retryIndex = retryMessageId
      ? initialState.messages.findIndex((message) => message.id === retryMessageId)
      : -1;
    if (retryMessageId && retryIndex < 0) return;

    const parsedAgents = parseAgentMentions(userMsgContent);
    const selectedAgents = opts.agentsOverride ?? parsedAgents;
    const queryToSend = parsedAgents.length
      ? (userMsgContent.replace(/(?:^|\s)@[A-Za-z_]+/g, ' ').replace(/\s+/g, ' ').trim() || userMsgContent)
      : userMsgContent;
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
    const pendingHandoff = initialState.takePendingChatHandoffContext(requestSessionId);

    const isRequestSessionActive = () => useStore.getState().sessionId === requestSessionId;
    const updateScopedMessage = (id: string, patch: Partial<Message>) => {
      useStore.getState().updateMessageInSession(requestSessionId, id, patch);
    };

    // 2. 历史与消息槽位：发送新增消息，重试原位复用 assistant 消息。
    const historySource = retryIndex >= 0
      ? initialState.messages.slice(0, retryIndex)
      : initialState.messages;
    const history = historySource
      .filter((message) => message.role === 'user' || message.role === 'assistant')
      .slice(-DEFAULT_HISTORY_LIMIT)
      .map((message) => ({ role: message.role, content: message.content }));

    if (!retryMessageId) {
      initialState.addMessageToSession(requestSessionId, {
        id: uuidv4(), role: 'user', content: userMsgContent, timestamp: Date.now(),
      });
    }
    const aiMsgId = retryMessageId || uuidv4();
    if (retryMessageId) {
      updateScopedMessage(aiMsgId, { content: '', isLoading: true });
    } else {
      initialState.addMessageToSession(requestSessionId, {
        id: aiMsgId, role: 'assistant', content: '', timestamp: Date.now(), isLoading: true,
      });
    }

    const store = useStore.getState();
    store.setSessionLoading(requestSessionId, true);
    if (isRequestSessionActive()) store.setStatus(retryMessageId ? zh.chat.retrying : zh.chat.streaming);
    const streamController = new AbortController();
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
    const outputMode = opts.outputMode ?? 'chat';
    const requestStartedAt = Date.now();

    // 3. 断流后的报告回捞。
    const recoverReportIfAvailable = async (): Promise<boolean> => {
      try {
        const index = await apiClient.listReportIndex({ sessionId: requestSessionId, limit: 1, includeBlocked: true });
        const latest = index.items?.[0];
        if (!latest?.report_id) return false;
        const timestamp = latest.generated_at || latest.created_at || latest.updated_at || '';
        if (timestamp) {
          const parsed = Date.parse(timestamp);
          if (Number.isFinite(parsed) && parsed + 120000 < requestStartedAt) return false;
        }
        const replay = await apiClient.getReportReplay({
          sessionId: requestSessionId,
          reportId: latest.report_id,
          includeBlocked: true,
        });
        if (!replay?.report) return false;
        updateScopedMessage(aiMsgId, {
          content: replay.report.summary || fullContent || zh.execution.recovered,
          isLoading: false,
          report: replay.report,
          evidence_pool: replay.citations,
        });
        if (isRequestSessionActive()) useStore.getState().setStatus(null);
        toast({ type: 'success', title: zh.chat.recoveredTitle, message: zh.chat.recoveredMessage });
        return true;
      } catch {
        return false;
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
      if (isRequestSessionActive()) current.setStatus(zh.chat.stopped);
      current.addAgentLog({
        id: uuidv4(), timestamp: new Date().toISOString(), source: 'system', level: 'warn', message: zh.chat.stopped,
      });
      current.updateAgentStatus('supervisor', {
        status: 'waiting', endTime: new Date().toISOString(), lastMessage: zh.chat.stopped,
      });
      if (execRunId) useExecutionStore.getState().completeExternalExecution({ runId: execRunId, status: 'cancelled' });
    };

    try {
      const dashboard = useDashboardStore.getState();
      const context: ChatContext = {};
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
      if (requestSessionId) {
        try {
          const portfolioSummary = await queryClient.fetchQuery({
            queryKey: ['portfolio-summary', requestSessionId],
            queryFn: () => apiClient.getPortfolioSummary(requestSessionId),
            staleTime: 30_000,
          });
          const positions = normalizePortfolioPositionsForChat(portfolioSummary.positions);
          if (positions.length > 0) context.positions = positions;
        } catch {
          // 持仓不可用时不阻断普通聊天，也不伪造空持仓。
        }
      }
      if (initialState.subscriptionEmail) context.user_email = initialState.subscriptionEmail;
      const streamContext = Object.keys(context).length > 0 ? context : undefined;
      const agentPreferences = getAgentPreferences();

      // 4. 所有发送/重试共用同一个 SSE 管线。
      await apiClient.sendMessageStream(
        {
          query: queryToSend,
          history,
          context: streamContext,
          options: {
            output_mode: outputMode,
            ...(outputMode === 'investment_report' ? { strict_selection: false } : {}),
            confirmation_mode: 'skip',
            trace_raw_override: initialState.traceRawEnabled ? 'on' : 'off',
            agent_preferences: agentPreferences,
            agents: selectedAgents.length ? selectedAgents : undefined,
          },
          session_id: requestSessionId || undefined,
        },
        {
          onToken: (token) => {
            const safeToken = typeof token === 'string' ? token : JSON.stringify(token);
            if (safeToken) {
              fullContent += safeToken;
              if (execRunId) useExecutionStore.getState().ingestExternalToken(execRunId, safeToken);
            }
            updateScopedMessage(aiMsgId, { content: fullContent, isLoading: true });
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
          onDone: async (report, thinking, meta) => {
            const degraded = meta?.degraded === true;
            const doneStep: ThinkingStep = {
              stage: 'done',
              message: zh.chat.analysisDone,
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
            if (isRequestSessionActive() && typeof meta?.session_id === 'string' && meta.session_id.trim() && meta.session_id !== requestSessionId) {
              useStore.getState().setSessionId(meta.session_id);
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
            const nextFocus = meta?.current_focus || report?.ticker || guessedTicker || null;
            if (nextFocus) useStore.getState().setTicker(nextFocus);
            updateScopedMessage(aiMsgId, {
              content: fullContent,
              isLoading: false,
              report,
              thinking: thinkingSteps,
              evidence_pool: meta?.evidence_pool ?? meta?.data?.evidence_pool,
              fallback_used: degraded,
              data_origin: degraded ? 'LLM' : undefined,
            });
            if (degraded) {
              toast({ type: 'warning', title: zh.chat.degradedTitle, message: zh.chat.degradedMessage });
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
                } else if (chartInfo.smartChart && !forceMulti) {
                  const smartTicker = tickers[0] || nextFocus || initialState.currentTicker || null;
                  if (smartTicker && !/<chart\s+/i.test(patched)) {
                    const { chartType, dataKind, title } = chartInfo.smartChart;
                    const result = await apiClient.getChartData(smartTicker, dataKind);
                    if (result?.success && result.data && Array.isArray(result.data.values) && result.data.values.length > 0) {
                      const safeTitle = (title || zh.chat.chartTitle(smartTicker)).replace(/"/g, '');
                      patched += `\n\n<chart type="${chartType}" title="${safeTitle}">${JSON.stringify(result.data)}</chart>`;
                      useStore.getState().setTicker(smartTicker);
                    }
                  }
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
          },
          onError: (error) => {
            terminalHandlingPromise = (async () => {
              if (await recoverReportIfAvailable()) return;
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
        },
        {
          traceRawEnabled: initialState.traceRawEnabled,
          signal: streamController.signal,
          onConnectionState: (state) => {
            if (!isRequestSessionActive()) return;
            const current = useStore.getState();
            if (state === 'reconnecting') current.setStatus(zh.chat.reconnecting);
            else if (state === 'connected') current.setStatus(zh.chat.streaming);
            else current.setStatus(zh.chat.streamInterrupted);
          },
        },
      );
      const pendingTerminalHandling = terminalHandlingPromise;
      if (pendingTerminalHandling) await pendingTerminalHandling;
      if (streamController.signal.aborted) finishAbortedStream();
    } catch (error) {
      if (streamController.signal.aborted) {
        finishAbortedStream();
        return;
      }
      updateScopedMessage(aiMsgId, {
        content: zh.chat.networkRequestFailed,
        isLoading: false,
      });
      const current = useStore.getState();
      if (isRequestSessionActive()) current.setStatus(zh.chat.requestFailed);
      toast({ type: 'error', title: zh.chat.requestFailed, message: zh.chat.requestFailedMessage });
      current.addAgentLog({
        id: uuidv4(), timestamp: new Date().toISOString(), source: 'system', level: 'error',
        message: error instanceof Error ? error.message : zh.chat.networkRequestFailed,
      });
    } finally {
      // 7. 会话级 loading/AbortController 收尾；executionStore 保持唯一进度真相源。
      const current = useStore.getState();
      current.setSessionLoading(requestSessionId, false);
      if (isRequestSessionActive()) {
        if (streamController.signal.aborted) current.setStatus(zh.chat.stopped);
        else current.setStatus(null);
        current.resetExecutionState();
      }
      current.setSessionAbortController(requestSessionId, null);
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
    await runChatStream(query, { retryMessageId: messageId, outputMode: 'chat' });
  }, [runChatStream, sessionId]);

  const stop = useCallback(() => useStore.getState().cancelChatStream(), []);

  return { send, retry, stop };
}
