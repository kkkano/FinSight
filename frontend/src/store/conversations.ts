import type { StateCreator } from 'zustand';
import type { AppState } from './stateTypes';
import type { ConversationServices } from './conversationPersistence';
import { sessionBelongsToIdentity, buildNewConversationSessionId, ownedSessionOrFallback } from './sessionIdentity';
import { EMPTY_CHAT_SESSION_STATUS, statusForSession, createInitialAgentStatuses } from './chatSession';
import { cancelPersist, flushPersist } from './persistScheduler';

export type ConversationsSlice = Pick<AppState, "conversationSummaries" | "sessionId" | "flushConversationSync" | "clearConversationContext" | "startNewChat" | "setSessionId" | "selectConversation" | "deleteConversation">;

export const createConversationsSlice = (services: ConversationServices, initialSessionId: string): StateCreator<AppState, [], [], ConversationsSlice> => (set, get) => {
  const useStore = { getState: get, setState: set };
  const { WELCOME_MESSAGE, cancelConversationSync, createBackendConversation, flushConversationSync, deleteBackendConversation, loadConversationSummaries, upsertConversationSummary, loadMessagesForSession, getInitialMessages, needsBackendHistory, hydrateMessagesFromBackend, persistConversationSummaries, clearPersistedMessages, clearPersistedConversation } = services;
  return {
conversationSummaries: loadConversationSummaries(initialSessionId, getInitialMessages(initialSessionId)),

sessionId: initialSessionId,

flushConversationSync,

clearConversationContext: () =>
    set((state) => {
      const activeController = state.abortControllersBySession[state.sessionId] || state.abortController;
      activeController?.abort();
      clearPersistedMessages(state.sessionId);
      createBackendConversation(state.sessionId, [WELCOME_MESSAGE]);
      const conversationSummaries = upsertConversationSummary(
        state.conversationSummaries,
        state.sessionId,
        [WELCOME_MESSAGE],
      );
      return {
        messages: [WELCOME_MESSAGE],
        conversationSummaries,
        isChatLoading: false,
        chatLoadingBySession: {
          ...state.chatLoadingBySession,
          [state.sessionId]: false,
        },
        chatStatusBySession: {
          ...state.chatStatusBySession,
          [state.sessionId]: EMPTY_CHAT_SESSION_STATUS,
        },
        statusMessage: null,
        statusSince: null,
        executionProgress: null,
        currentStep: null,
        abortController: null,
        abortControllersBySession: {
          ...state.abortControllersBySession,
          [state.sessionId]: null,
        },
        currentTicker: null,
        draft: '',
        draftBySession: {
          ...state.draftBySession,
          [state.sessionId]: '',
        },
        agentLogs: [],
        agentStatuses: createInitialAgentStatuses(),
        rawEvents: [],
        requestMetrics: {
          llmTotalCalls: 0,
          toolTotalCalls: 0,
          updatedAt: null,
        },
      };
    }),

startNewChat: () => {
    // FE-01：切走前把当前会话 pending 的去抖写盘落定（此刻 state 仍指向旧会话，能正确落盘）
    flushPersist(useStore.getState().sessionId);
    return set((state) => {
      const nextSessionId = buildNewConversationSessionId(state.authIdentity);
      if (typeof window !== 'undefined') {
        window.localStorage.setItem('finsight-session-id', nextSessionId);
      }
      createBackendConversation(nextSessionId, [WELCOME_MESSAGE]);
      const conversationSummaries = upsertConversationSummary(
        state.conversationSummaries,
        nextSessionId,
        [WELCOME_MESSAGE],
      );
      const sessionStatus = statusForSession(state.chatStatusBySession, nextSessionId);
      return {
        sessionId: nextSessionId,
        messages: [WELCOME_MESSAGE],
        conversationSummaries,
        isChatLoading: Boolean(state.chatLoadingBySession[nextSessionId]),
        statusMessage: sessionStatus.statusMessage,
        statusSince: sessionStatus.statusSince,
        executionProgress: sessionStatus.executionProgress,
        currentStep: sessionStatus.currentStep,
        abortController: state.abortControllersBySession[nextSessionId] || null,
        currentTicker: null,
        draft: state.draftBySession[nextSessionId] || '',
        agentLogs: [],
        agentStatuses: createInitialAgentStatuses(),
        rawEvents: [],
        requestMetrics: {
          llmTotalCalls: 0,
          toolTotalCalls: 0,
          updatedAt: null,
        },
      };
    });
  },

setSessionId: (sessionId) => {
    let needHydrate = false;
    let hydrateSid = '';
    set((state) => {
      const normalized = ownedSessionOrFallback(sessionId, state.authIdentity);
      const messages = loadMessagesForSession(normalized, { preserveLoading: Boolean(state.chatLoadingBySession[normalized]) });
      if (typeof window !== 'undefined') {
        window.localStorage.setItem('finsight-session-id', normalized);
      }
      // 空历史或中断回答只读取服务器快照，不能用旧本地内容覆盖它。
      if (needsBackendHistory(messages) && !state.chatLoadingBySession[normalized]) {
        needHydrate = true;
        hydrateSid = normalized;
      }
      const sessionStatus = statusForSession(state.chatStatusBySession, normalized);
      return {
        sessionId: normalized,
        messages,
        conversationSummaries: upsertConversationSummary(state.conversationSummaries, normalized, messages),
        isChatLoading: Boolean(state.chatLoadingBySession[normalized]),
        statusMessage: sessionStatus.statusMessage,
        statusSince: sessionStatus.statusSince,
        executionProgress: sessionStatus.executionProgress,
        currentStep: sessionStatus.currentStep,
        abortController: state.abortControllersBySession[normalized] || null,
        draft: state.draftBySession[normalized] || '',
      };
    });
    if (needHydrate) hydrateMessagesFromBackend(hydrateSid);
  },

selectConversation: (sessionId) => {
    // FE-01：切走前先把旧会话的 pending 去抖写盘落定，防止读到半新半旧
    flushPersist(useStore.getState().sessionId);
    let needHydrate = false;
    let hydrateSid = '';
    set((state) => {
      const normalized = String(sessionId || '').trim();
      if (!normalized || !sessionBelongsToIdentity(normalized, state.authIdentity)) return {};
      const messages = loadMessagesForSession(normalized, { preserveLoading: Boolean(state.chatLoadingBySession[normalized]) });
      if (typeof window !== 'undefined') {
        window.localStorage.setItem('finsight-session-id', normalized);
      }
      if (needsBackendHistory(messages) && !state.chatLoadingBySession[normalized]) {
        needHydrate = true;
        hydrateSid = normalized;
      }
      const sessionStatus = statusForSession(state.chatStatusBySession, normalized);
      return {
        sessionId: normalized,
        messages,
        conversationSummaries: upsertConversationSummary(state.conversationSummaries, normalized, messages),
        isChatLoading: Boolean(state.chatLoadingBySession[normalized]),
        statusMessage: sessionStatus.statusMessage,
        statusSince: sessionStatus.statusSince,
        executionProgress: sessionStatus.executionProgress,
        currentStep: sessionStatus.currentStep,
        abortController: state.abortControllersBySession[normalized] || null,
        currentTicker: null,
        draft: state.draftBySession[normalized] || '',
        agentLogs: [],
        agentStatuses: createInitialAgentStatuses(),
        rawEvents: [],
        requestMetrics: {
          llmTotalCalls: 0,
          toolTotalCalls: 0,
          updatedAt: null,
        },
      };
    });
    if (needHydrate) hydrateMessagesFromBackend(hydrateSid);
  },

deleteConversation: (sessionId) =>
    set((state) => {
      const normalized = String(sessionId || '').trim();
      if (!normalized || !sessionBelongsToIdentity(normalized, state.authIdentity)) return {};
      if (normalized === state.sessionId) {
        const activeController = state.abortControllersBySession[normalized] || state.abortController;
        activeController?.abort();
      }
      cancelPersist(normalized); // FE-01：丢弃 pending 写盘，防止定时器把已删会话写回
      cancelConversationSync(normalized);
      deleteBackendConversation(normalized);
      clearPersistedConversation(normalized);
      const remaining = state.conversationSummaries
        .filter((item) => item.sessionId !== normalized)
        .sort((a, b) => b.updatedAt - a.updatedAt);
      const nextSessionId = normalized === state.sessionId
        ? (remaining[0]?.sessionId || buildNewConversationSessionId(state.authIdentity))
        : state.sessionId;
      const nextMessages = normalized === state.sessionId
        ? loadMessagesForSession(nextSessionId)
        : state.messages;
      const nextSummaries = remaining.length > 0 || nextSessionId === state.sessionId
        ? remaining
        : upsertConversationSummary([], nextSessionId, nextMessages);
      persistConversationSummaries(nextSummaries);
      if (typeof window !== 'undefined') {
        window.localStorage.setItem('finsight-session-id', nextSessionId);
      }
      if (normalized === state.sessionId && nextSessionId !== normalized) {
        createBackendConversation(nextSessionId, nextMessages);
      }
      const nextSessionStatus = statusForSession(state.chatStatusBySession, nextSessionId);
      const pendingChatHandoffContextBySession = { ...state.pendingChatHandoffContextBySession };
      delete pendingChatHandoffContextBySession[normalized];
      return {
        sessionId: nextSessionId,
        messages: nextMessages,
        conversationSummaries: nextSummaries,
        isChatLoading: normalized === state.sessionId ? Boolean(state.chatLoadingBySession[nextSessionId]) : state.isChatLoading,
        chatLoadingBySession: {
          ...state.chatLoadingBySession,
          [normalized]: false,
        },
        chatStatusBySession: {
          ...state.chatStatusBySession,
          [normalized]: EMPTY_CHAT_SESSION_STATUS,
        },
        statusMessage: normalized === state.sessionId ? nextSessionStatus.statusMessage : state.statusMessage,
        statusSince: normalized === state.sessionId ? nextSessionStatus.statusSince : state.statusSince,
        executionProgress: normalized === state.sessionId ? nextSessionStatus.executionProgress : state.executionProgress,
        currentStep: normalized === state.sessionId ? nextSessionStatus.currentStep : state.currentStep,
        abortController: normalized === state.sessionId ? (state.abortControllersBySession[nextSessionId] || null) : state.abortController,
        abortControllersBySession: {
          ...state.abortControllersBySession,
          [normalized]: null,
        },
        currentTicker: normalized === state.sessionId ? null : state.currentTicker,
        draft: normalized === state.sessionId ? (state.draftBySession[nextSessionId] || '') : state.draft,
        draftBySession: {
          ...state.draftBySession,
          [normalized]: '',
        },
        pendingChatHandoffContextBySession,
        agentLogs: normalized === state.sessionId ? [] : state.agentLogs,
        agentStatuses: normalized === state.sessionId ? createInitialAgentStatuses() : state.agentStatuses,
        rawEvents: normalized === state.sessionId ? [] : state.rawEvents,
      };
    })
  };
};
