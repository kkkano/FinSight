import type { StateCreator } from 'zustand';
import type { AppState } from './stateTypes';
import type { AgentLogSource, AgentStatus, TraceViewMode } from '../types';
import type { ChatSessionStatus } from './stateTypes';
import type { ConversationServices } from './conversationPersistence';
import { sessionBelongsToIdentity } from './sessionIdentity';
import { cancelPersist, schedulePersist } from './persistScheduler';
import { zh } from '../locales/zh';

export const createInitialAgentStatuses = (): Record<AgentLogSource, AgentStatus> => ({
  supervisor: { source: 'supervisor', status: 'idle' },
  router: { source: 'router', status: 'idle' },
  gate: { source: 'gate', status: 'idle' },
  planner: { source: 'planner', status: 'idle' },
  news_agent: { source: 'news_agent', status: 'idle' },
  price_agent: { source: 'price_agent', status: 'idle' },
  fundamental_agent: { source: 'fundamental_agent', status: 'idle' },
  technical_agent: { source: 'technical_agent', status: 'idle' },
  macro_agent: { source: 'macro_agent', status: 'idle' },
  deep_search_agent: { source: 'deep_search_agent', status: 'idle' },
  forum: { source: 'forum', status: 'idle' },
  system: { source: 'system', status: 'idle' },
});

export const EMPTY_CHAT_SESSION_STATUS: ChatSessionStatus = {
  statusMessage: null,
  statusSince: null,
  executionProgress: null,
  currentStep: null,
};

export const statusForSession = (
  statuses: Record<string, ChatSessionStatus>,
  sessionId: string,
): ChatSessionStatus => statuses[sessionId] || EMPTY_CHAT_SESSION_STATUS;

export const getInitialTraceRawEnabled = (): boolean => {
  if (typeof window === 'undefined') return false;
  const raw = window.localStorage.getItem('finsight-trace-raw-enabled');
  if (raw === null) return false;
  return raw === 'true';
};

export const getInitialTraceRawShowRawJson = (): boolean => {
  if (typeof window === 'undefined') return false;
  const raw = window.localStorage.getItem('finsight-trace-raw-show-json');
  if (raw === null) return false;
  return raw === 'true';
};

export const getInitialTraceViewMode = (): TraceViewMode => {
  // P2-2: 执行追踪（专家模式）默认可见——这是 FinSight 的护城河
  // （用户关心"AI 怎么得出结论"），不再藏在循环切换的彩蛋里
  if (typeof window === 'undefined') return 'expert';
  const raw = window.localStorage.getItem('finsight-trace-view-mode');
  return raw === 'user' || raw === 'expert' || raw === 'dev' ? (raw as TraceViewMode) : 'expert';
};

export type ChatSessionSlice = Pick<AppState, "messages" | "isChatLoading" | "chatLoadingBySession" | "chatStatusBySession" | "statusMessage" | "statusSince" | "executionProgress" | "currentStep" | "currentTicker" | "abortController" | "abortControllersBySession" | "agentLogs" | "agentStatuses" | "isAgentLogsPanelOpen" | "rawEvents" | "isConsoleOpen" | "traceRawEnabled" | "traceViewMode" | "traceRawShowRawJson" | "requestMetrics" | "addMessage" | "addMessageToSession" | "updateMessage" | "updateMessageInSession" | "updateLastMessage" | "removeMessage" | "setLoading" | "setSessionLoading" | "setStatus" | "setExecutionState" | "resetExecutionState" | "setTicker" | "setAbortController" | "setSessionAbortController" | "cancelChatStream" | "addAgentLog" | "updateAgentStatus" | "clearAgentLogs" | "setAgentLogsPanelOpen" | "addRawEvent" | "clearRawEvents" | "setConsoleOpen" | "setTraceRawEnabled" | "setTraceViewMode" | "setTraceRawShowRawJson" | "setRequestMetrics">;

export const createChatSessionSlice = (services: ConversationServices, initial: {
 initialSessionId: string; initialTraceRawEnabled: boolean; initialTraceViewMode: TraceViewMode; initialTraceRawShowRawJson: boolean;
}): StateCreator<AppState, [], [], ChatSessionSlice> => (set, get) => {
  const useStore = { getState: get, setState: set };
  const { upsertConversationSummary, loadMessagesForSession, getInitialMessages, persistMessages, appendMessageForSession, patchMessageForSession } = services;
  const { initialSessionId, initialTraceRawEnabled, initialTraceViewMode, initialTraceRawShowRawJson } = initial;
  return {
messages: getInitialMessages(initialSessionId),

isChatLoading: false,

chatLoadingBySession: {},

chatStatusBySession: {},

statusMessage: null,

statusSince: null,

executionProgress: null,

currentStep: null,

currentTicker: null,

abortController: null,

abortControllersBySession: {},

// Agent Logs 初始状态
  agentLogs: [],

agentStatuses: createInitialAgentStatuses(),

isAgentLogsPanelOpen: true,

// Raw SSE Events 初始状态
  rawEvents: [],

isConsoleOpen: true,

traceRawEnabled: initialTraceRawEnabled,

traceViewMode: initialTraceViewMode,

traceRawShowRawJson: initialTraceRawShowRawJson,

requestMetrics: {
    llmTotalCalls: 0,
    toolTotalCalls: 0,
    updatedAt: null,
  },

addMessage: (message) =>
    set((state) => {
      const next = appendMessageForSession(state.messages, message);
      persistMessages(next, state.sessionId);
      return {
        messages: next,
        conversationSummaries: upsertConversationSummary(state.conversationSummaries, state.sessionId, next),
      };
    }),

addMessageToSession: (sessionId, message) =>
    set((state) => {
      const normalized = String(sessionId || '').trim();
      if (!normalized || !sessionBelongsToIdentity(normalized, state.authIdentity)) return {};
      const baseMessages = normalized === state.sessionId
        ? state.messages
        : loadMessagesForSession(normalized);
      const next = appendMessageForSession(baseMessages, message);
      persistMessages(next, normalized);
      return {
        messages: normalized === state.sessionId ? next : state.messages,
        conversationSummaries: upsertConversationSummary(state.conversationSummaries, normalized, next),
      };
    }),

updateMessage: (id, patch) =>
    set((state) => {
      const next = patchMessageForSession(state.messages, id, patch);
      const finalized = patch.isLoading === false;
      if (!finalized) {
        // FE-01：流式中间态的写盘与摘要更新去抖合并，消息 state 照常更新
        schedulePersist(state.sessionId, () => {
          const latest = useStore.getState();
          if (latest.sessionId !== state.sessionId) return; // 已切会话，等收尾路径落盘
          persistMessages(latest.messages, latest.sessionId, { syncBackend: false });
          useStore.setState({
            conversationSummaries: upsertConversationSummary(
              latest.conversationSummaries,
              latest.sessionId,
              latest.messages,
            ),
          });
        });
        return { messages: next };
      }
      cancelPersist(state.sessionId);
      persistMessages(next, state.sessionId, { syncBackend: true });
      return {
        messages: next,
        conversationSummaries: upsertConversationSummary(state.conversationSummaries, state.sessionId, next),
      };
    }),

updateMessageInSession: (sessionId, id, patch, options = {}) =>
    set((state) => {
      const normalized = String(sessionId || '').trim();
      if (!normalized || !sessionBelongsToIdentity(normalized, state.authIdentity)) return {};
      const isActiveSession = normalized === state.sessionId;
      let baseMessages = isActiveSession
        ? state.messages
        : loadMessagesForSession(normalized, { preserveLoading: Boolean(state.chatLoadingBySession[normalized]) });
      const recovery = options.recovery;
      if (recovery && (recovery.controller.signal.aborted
          || (state.authIdentity?.userId || null) !== recovery.ownerId
          || state.abortControllersBySession[normalized] !== recovery.controller
          || !state.chatLoadingBySession[normalized]
          || !baseMessages.some((message) => message.id === recovery.userMessageId && message.role === 'user'))) return {};
      let targetId = id;
      if (!baseMessages.some((message) => message.id === targetId)) {
        // 只有仍拥有问题和 AbortController 的本轮正文可恢复；图表等补挂不传此守卫。
        if (!recovery || !patch.content?.trim()) return {};
        const counterpart = baseMessages.find((message) => message.role === 'assistant'
          && message.replyTo === recovery.userMessageId);
        if (counterpart) {
          if (counterpart.runId !== recovery.runId) return {};
          targetId = counterpart.id;
        } else {
          baseMessages = [...baseMessages, { id, role: 'assistant', content: '', timestamp: recovery.timestamp,
            runId: recovery.runId, replyTo: recovery.userMessageId, isLoading: true }];
        }
      }
      if (recovery && baseMessages.some((message) => message.id === targetId
        && (message.role !== 'assistant' || message.runId !== recovery.runId || message.replyTo !== recovery.userMessageId))) return {};
      const next = patchMessageForSession(baseMessages, targetId, patch);
      const finalized = patch.isLoading === false;
      if (!finalized && isActiveSession) {
        // FE-01：流式中间态去抖（仅当前会话；跨会话更新低频，保持原直写路径）
        schedulePersist(normalized, () => {
          const latest = useStore.getState();
          if (latest.sessionId !== normalized) return; // 已切走：patch 含全量 content，收尾路径会补齐
          persistMessages(latest.messages, normalized, { syncBackend: false });
          useStore.setState({
            conversationSummaries: upsertConversationSummary(latest.conversationSummaries, normalized, latest.messages),
          });
        });
        return { messages: next };
      }
      if (finalized) cancelPersist(normalized);
      persistMessages(next, normalized, { syncBackend: finalized && options.syncBackend !== false });
      return {
        messages: isActiveSession ? next : state.messages,
        conversationSummaries: upsertConversationSummary(state.conversationSummaries, normalized, next),
      };
    }),

updateLastMessage: (content) =>
    set((state) => {
      if (state.messages.length === 0) return {};
      const next = state.messages.map((m, i) =>
        i === state.messages.length - 1 ? { ...m, content } : m,
      );
      return { messages: next };
    }),

removeMessage: (id) =>
    set((state) => {
      const next = state.messages.filter((m) => m.id !== id);
      persistMessages(next, state.sessionId);
      return {
        messages: next,
        conversationSummaries: upsertConversationSummary(state.conversationSummaries, state.sessionId, next),
      };
    }),

setLoading: (loading) =>
    set((state) => ({
      isChatLoading: loading,
      chatLoadingBySession: {
        ...state.chatLoadingBySession,
        [state.sessionId]: loading,
      },
    })),

setSessionLoading: (sessionId, loading) =>
    set((state) => {
      const normalized = String(sessionId || '').trim();
      if (!normalized || !sessionBelongsToIdentity(normalized, state.authIdentity)) return {};
      const nextStatuses = loading
        ? state.chatStatusBySession
        : {
            ...state.chatStatusBySession,
            [normalized]: EMPTY_CHAT_SESSION_STATUS,
          };
      return {
        chatLoadingBySession: {
          ...state.chatLoadingBySession,
          [normalized]: loading,
        },
        chatStatusBySession: nextStatuses,
        isChatLoading: normalized === state.sessionId ? loading : state.isChatLoading,
        statusMessage: normalized === state.sessionId && !loading ? null : state.statusMessage,
        statusSince: normalized === state.sessionId && !loading ? null : state.statusSince,
        executionProgress: normalized === state.sessionId && !loading ? null : state.executionProgress,
        currentStep: normalized === state.sessionId && !loading ? null : state.currentStep,
      };
    }),

setStatus: (message) =>
    set((state) => {
      const nextStatus = {
        ...statusForSession(state.chatStatusBySession, state.sessionId),
        statusMessage: message,
        statusSince: message ? Date.now() : null,
      };
      return {
        statusMessage: nextStatus.statusMessage,
        statusSince: nextStatus.statusSince,
        chatStatusBySession: {
          ...state.chatStatusBySession,
          [state.sessionId]: nextStatus,
        },
      };
    }),

setExecutionState: (step, progress = null) =>
    set((state) => {
      const nextProgress = progress === null ? null : Math.max(0, Math.min(100, progress));
      const nextStatus = {
        ...statusForSession(state.chatStatusBySession, state.sessionId),
        currentStep: step,
        executionProgress: nextProgress,
      };
      return {
        currentStep: step,
        executionProgress: nextProgress,
        chatStatusBySession: {
          ...state.chatStatusBySession,
          [state.sessionId]: nextStatus,
        },
      };
    }),

resetExecutionState: () =>
    set((state) => {
      const nextStatus = {
        ...statusForSession(state.chatStatusBySession, state.sessionId),
        currentStep: null,
        executionProgress: null,
      };
      return {
        currentStep: null,
        executionProgress: null,
        chatStatusBySession: {
          ...state.chatStatusBySession,
          [state.sessionId]: nextStatus,
        },
      };
    }),

setTicker: (ticker) => set({ currentTicker: ticker }),

setAbortController: (controller) =>
    set((state) => ({
      abortController: controller,
      abortControllersBySession: {
        ...state.abortControllersBySession,
        [state.sessionId]: controller,
      },
    })),

setSessionAbortController: (sessionId, controller) =>
    set((state) => {
      const normalized = String(sessionId || '').trim();
      if (!normalized || !sessionBelongsToIdentity(normalized, state.authIdentity)) return {};
      return {
        abortControllersBySession: {
          ...state.abortControllersBySession,
          [normalized]: controller,
        },
        abortController: normalized === state.sessionId ? controller : state.abortController,
      };
    }),

cancelChatStream: () =>
    set((state) => {
      const progress = state.executionProgress;
      const activeController = state.abortControllersBySession[state.sessionId] || state.abortController;
      activeController?.abort();
      return {
        abortController: null,
        abortControllersBySession: {
          ...state.abortControllersBySession,
          [state.sessionId]: null,
        },
        chatLoadingBySession: {
          ...state.chatLoadingBySession,
          [state.sessionId]: false,
        },
        isChatLoading: false,
        statusMessage: zh.chat.stopped,
        statusSince: Date.now(),
        currentStep: zh.chat.stoppedLabel,
        executionProgress: progress,
        chatStatusBySession: {
          ...state.chatStatusBySession,
          [state.sessionId]: {
            statusMessage: zh.chat.stopped,
            statusSince: Date.now(),
            currentStep: zh.chat.stoppedLabel,
            executionProgress: progress,
          },
        },
      };
    }),

// Agent Logs Actions
  addAgentLog: (log) =>
    set((state) => ({
      // 保留最近 500 条日志，防止内存溢出
      agentLogs: [...state.agentLogs, log].slice(-500),
    })),

updateAgentStatus: (source, status) =>
    set((state) => ({
      agentStatuses: {
        ...state.agentStatuses,
        [source]: {
          ...state.agentStatuses[source],
          ...status,
          source,
        },
      },
    })),

clearAgentLogs: () =>
    set(() => ({
      agentLogs: [],
      agentStatuses: createInitialAgentStatuses(),
    })),

setAgentLogsPanelOpen: (open) =>
    set(() => ({ isAgentLogsPanelOpen: open })),

// Raw SSE Events Actions
  addRawEvent: (event) =>
    set((state) => ({
      rawEvents: [...state.rawEvents, event].slice(-1000),
    })),

clearRawEvents: () =>
    set(() => ({ rawEvents: [] })),

setConsoleOpen: (open) =>
    set(() => ({ isConsoleOpen: open })),

setTraceRawEnabled: (enabled) =>
    set(() => {
      if (typeof window !== 'undefined') {
        window.localStorage.setItem('finsight-trace-raw-enabled', String(Boolean(enabled)));
      }
      return { traceRawEnabled: Boolean(enabled) };
    }),

setTraceViewMode: (mode) =>
    set(() => {
      if (typeof window !== 'undefined') {
        window.localStorage.setItem('finsight-trace-view-mode', mode);
      }
      return { traceViewMode: mode };
    }),

setTraceRawShowRawJson: (show) =>
    set(() => {
      if (typeof window !== 'undefined') {
        window.localStorage.setItem('finsight-trace-raw-show-json', String(Boolean(show)));
      }
      return { traceRawShowRawJson: Boolean(show) };
    }),

setRequestMetrics: (metrics) =>
    set((state) => ({
      requestMetrics: {
        ...state.requestMetrics,
        ...metrics,
      },
    }))
  };
};
