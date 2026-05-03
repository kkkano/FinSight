import { beforeEach, describe, expect, it } from 'vitest';

import { useStore } from './useStore';

describe('useStore conversation lifecycle', () => {
  beforeEach(() => {
    if (typeof window !== 'undefined') {
      window.localStorage.clear();
    }
    const state = useStore.getState();
    state.setSessionId('public:test-user:default');
    state.clearConversationContext();
  });

  it('clears the current conversation context without rotating session id', () => {
    const state = useStore.getState();
    const controller = new AbortController();

    state.addMessage({ id: 'user-1', role: 'user', content: 'AAPL outlook', timestamp: 1 });
    state.setDraft('draft query');
    state.setTicker('AAPL');
    state.setStatus('Running');
    state.setExecutionState('Searching', 42);
    state.setLoading(true);
    state.setAbortController(controller);

    state.clearConversationContext();

    const next = useStore.getState();
    expect(controller.signal.aborted).toBe(true);
    expect(next.sessionId).toBe('public:test-user:default');
    expect(next.messages).toHaveLength(1);
    expect(next.messages[0].id).toBe('welcome');
    expect(next.draft).toBe('');
    expect(next.currentTicker).toBeNull();
    expect(next.isChatLoading).toBe(false);
    expect(next.statusMessage).toBeNull();
    expect(next.executionProgress).toBeNull();
    expect(next.abortController).toBeNull();
  });

  it('starts a new chat by rotating session id and resetting transient state', () => {
    const before = useStore.getState();
    before.addMessage({ id: 'user-1', role: 'user', content: 'TSLA news', timestamp: 1 });
    before.setDraft('draft query');
    before.setTicker('TSLA');

    before.startNewChat();

    const next = useStore.getState();
    expect(next.sessionId).not.toBe('public:test-user:default');
    expect(next.messages).toHaveLength(1);
    expect(next.messages[0].id).toBe('welcome');
    expect(next.draft).toBe('');
    expect(next.currentTicker).toBeNull();
    expect(next.isChatLoading).toBe(false);
  });

  it('keeps previous chats selectable after starting a new chat', () => {
    const before = useStore.getState();
    before.addMessage({ id: 'user-1', role: 'user', content: 'TSLA news', timestamp: 10 });
    const originalSession = before.sessionId;

    before.startNewChat();

    const afterNew = useStore.getState();
    expect(afterNew.sessionId).not.toBe(originalSession);
    expect(afterNew.conversationSummaries.some((item) => item.sessionId === originalSession)).toBe(true);
    expect(afterNew.conversationSummaries.some((item) => item.sessionId === afterNew.sessionId)).toBe(true);

    afterNew.selectConversation(originalSession);

    const restored = useStore.getState();
    expect(restored.sessionId).toBe(originalSession);
    expect(restored.messages.some((message) => message.content === 'TSLA news')).toBe(true);
  });

  it('deletes a stored conversation from the switcher', () => {
    const state = useStore.getState();
    state.addMessage({ id: 'user-1', role: 'user', content: 'AAPL outlook', timestamp: 10 });
    const originalSession = state.sessionId;
    state.startNewChat();

    useStore.getState().deleteConversation(originalSession);

    const next = useStore.getState();
    expect(next.sessionId).not.toBe(originalSession);
    expect(next.conversationSummaries.some((item) => item.sessionId === originalSession)).toBe(false);
  });

  it('marks chat stream as stopped when cancelling active generation', () => {
    const state = useStore.getState();
    const controller = new AbortController();
    state.setLoading(true);
    state.setStatus('Streaming response...');
    state.setExecutionState('Searching', 40);
    state.setAbortController(controller);

    state.cancelChatStream();

    const next = useStore.getState();
    expect(controller.signal.aborted).toBe(true);
    expect(next.isChatLoading).toBe(false);
    expect(next.statusMessage).toBe('已停止生成，保留已完成的结果。');
    expect(next.currentStep).toBe('已停止生成');
    expect(next.executionProgress).toBe(40);
    expect(next.abortController).toBeNull();
  });
});
