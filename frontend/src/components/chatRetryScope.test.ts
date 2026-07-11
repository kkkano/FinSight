import { beforeEach, describe, expect, it } from 'vitest';

import { createChatRetryScope } from './chatRetryScope';
import { useStore } from '../store/useStore';

describe('chat retry request scope', () => {
  beforeEach(() => {
    const state = useStore.getState();
    state.setSessionId('public:retry-user:session-a');
    state.clearConversationContext();
  });

  it('keeps a late retry result attached to its original conversation', () => {
    const state = useStore.getState();
    const requestSessionId = state.sessionId;
    state.addMessage({ id: 'user-a', role: 'user', content: 'AAPL retry', timestamp: 1 });
    state.addMessage({ id: 'assistant-a', role: 'assistant', content: 'old answer', timestamp: 2 });
    const scope = createChatRetryScope(requestSessionId, useStore);

    state.startNewChat();
    const activeSessionId = useStore.getState().sessionId;
    expect(activeSessionId).not.toBe(requestSessionId);

    scope.updateMessage('assistant-a', { content: 'retried answer', isLoading: false });
    scope.addMessage({ id: 'note-a', role: 'assistant', content: 'retry note', timestamp: 3 });
    scope.setLoading(false);

    expect(useStore.getState().sessionId).toBe(activeSessionId);
    expect(useStore.getState().messages.some((message) => message.content === 'retried answer')).toBe(false);
    expect(useStore.getState().messages.some((message) => message.content === 'retry note')).toBe(false);

    useStore.getState().selectConversation(requestSessionId);
    expect(useStore.getState().messages.some((message) => message.content === 'retried answer')).toBe(true);
    expect(useStore.getState().messages.some((message) => message.content === 'retry note')).toBe(true);
  });

  it('drops all late retry updates after the original conversation is deleted', () => {
    const state = useStore.getState();
    const requestSessionId = state.sessionId;
    state.addMessage({ id: 'user-delete', role: 'user', content: 'delete me', timestamp: 1 });
    state.addMessage({ id: 'assistant-delete', role: 'assistant', content: 'old answer', timestamp: 2 });
    const scope = createChatRetryScope(requestSessionId, useStore);

    state.startNewChat();
    useStore.getState().deleteConversation(requestSessionId);
    const loadingBeforeLateUpdates = useStore.getState().chatLoadingBySession[requestSessionId];
    scope.updateMessage('assistant-delete', { content: 'late answer', isLoading: false });
    scope.addMessage({ id: 'late-error', role: 'assistant', content: 'late retry error', timestamp: 3 });
    scope.setLoading(false);

    const next = useStore.getState();
    expect(next.conversationSummaries.some((item) => item.sessionId === requestSessionId)).toBe(false);
    expect(next.chatLoadingBySession[requestSessionId]).toBe(loadingBeforeLateUpdates);
  });
});
