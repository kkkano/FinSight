import type { Message } from '../types';

type RetryStoreState = {
  sessionId: string;
  conversationSummaries: Array<{ sessionId: string }>;
  updateMessageInSession: (sessionId: string, id: string, patch: Partial<Message>) => void;
  addMessageToSession: (sessionId: string, message: Message) => void;
  setSessionLoading: (sessionId: string, loading: boolean) => void;
};

type RetryStore = {
  getState: () => RetryStoreState;
};

export function createChatRetryScope(requestSessionId: string, store: RetryStore) {
  const isAlive = () => {
    const state = store.getState();
    return state.sessionId === requestSessionId
      || state.conversationSummaries.some((item) => item.sessionId === requestSessionId);
  };

  return {
    requestSessionId,
    isActive: () => store.getState().sessionId === requestSessionId,
    isAlive,
    updateMessage: (id: string, patch: Partial<Message>) => {
      if (!isAlive()) return;
      store.getState().updateMessageInSession(requestSessionId, id, patch);
    },
    addMessage: (message: Message) => {
      if (!isAlive()) return;
      store.getState().addMessageToSession(requestSessionId, message);
    },
    setLoading: (loading: boolean) => {
      if (!isAlive()) return;
      store.getState().setSessionLoading(requestSessionId, loading);
    },
  };
}
