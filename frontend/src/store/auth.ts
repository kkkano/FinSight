import type { StateCreator } from 'zustand';
import type { AppState } from './stateTypes';
import type { ConversationServices } from './conversationPersistence';
import type { EntryMode } from './stateTypes';
import { useRuntimeMemory } from './researchStream';
import { useModelSelectionStore } from './modelSelection';
import { readResearchPreferences } from './researchPreferences';
import { sessionBelongsToIdentity, buildUserSessionId, buildAnonymousSessionId } from './sessionIdentity';
import { createInitialAgentStatuses } from './chatSession';
import { cancelPersist } from './persistScheduler';

export type AuthSlice = Pick<AppState, "entryMode" | "authIdentity" | "setEntryMode" | "setAuthIdentity">;

export const createAuthSlice = (services: ConversationServices, initialEntryMode: EntryMode): StateCreator<AppState, [], [], AuthSlice> => (set, get) => {
  const useStore = { getState: get, setState: set };
  const { conversationSyncs, cancelConversationSync, loadConversationSummaries, loadMessagesForSession, needsBackendHistory, hydrateMessagesFromBackend, persistConversationSummaries } = services;
 return {
entryMode: initialEntryMode,

authIdentity: null,

setEntryMode: (mode) =>
    set(() => {
      if (typeof window !== 'undefined') {
        window.localStorage.setItem('finsight-entry-mode', mode);
      }
      return { entryMode: mode };
    }),

setAuthIdentity: (identity) => {
    useRuntimeMemory.getState().beginOwner(identity?.userId || null);
    set((state) => {
      const normalizedIdentity = identity?.userId
        ? { userId: String(identity.userId).trim(), email: identity.email }
        : null;
      const currentUserId = String(state.authIdentity?.userId || '').trim();
      const nextUserId = String(normalizedIdentity?.userId || '').trim();
      useModelSelectionStore.getState().setUser(nextUserId || null);
      if (currentUserId === nextUserId) return { authIdentity: normalizedIdentity };

      for (const sessionId of conversationSyncs.keys()) cancelConversationSync(sessionId);

      for (const controller of Object.values(state.abortControllersBySession)) {
        controller?.abort();
      }
      state.abortController?.abort();
      const priorSessionIds = new Set([
        state.sessionId,
        ...state.conversationSummaries.map((item) => item.sessionId),
        ...Object.keys(state.chatLoadingBySession),
      ]);
      for (const priorSessionId of priorSessionIds) cancelPersist(priorSessionId);

      const nextSessionId = normalizedIdentity?.userId
        ? (sessionBelongsToIdentity(state.sessionId, normalizedIdentity)
          ? state.sessionId : buildUserSessionId(normalizedIdentity.userId))
        : buildAnonymousSessionId();
      const nextMessages = loadMessagesForSession(nextSessionId);
      const nextSummaries = loadConversationSummaries(nextSessionId, nextMessages);
      persistConversationSummaries(nextSummaries);
      if (typeof window !== 'undefined') {
        window.localStorage.setItem('finsight-session-id', nextSessionId);
      }

      return {
        authIdentity: normalizedIdentity,
        ...readResearchPreferences(nextUserId),
        sessionId: nextSessionId,
        messages: nextMessages,
        conversationSummaries: nextSummaries,
        isChatLoading: false,
        chatLoadingBySession: {},
        chatStatusBySession: {},
        statusMessage: null,
        statusSince: null,
        executionProgress: null,
        currentStep: null,
        abortController: null,
        abortControllersBySession: {},
        currentTicker: null,
        draft: '',
        draftBySession: {},
        pendingChatHandoffContextBySession: {},
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
    const current = useStore.getState();
    if (current.authIdentity?.userId && needsBackendHistory(current.messages)
      && !current.chatLoadingBySession[current.sessionId]) hydrateMessagesFromBackend(current.sessionId);
  }
 };
};
