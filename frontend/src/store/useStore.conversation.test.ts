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

  it('keeps an in-flight conversation alive when switching to another chat', () => {
    const state = useStore.getState();
    const controller = new AbortController();
    const originalSession = state.sessionId;
    state.addMessage({ id: 'user-1', role: 'user', content: 'NVDA news', timestamp: 10 });
    state.addMessageToSession(originalSession, {
      id: 'ai-1',
      role: 'assistant',
      content: '',
      timestamp: 11,
      isLoading: true,
    });
    state.setSessionLoading(originalSession, true);
    state.setSessionAbortController(originalSession, controller);

    state.startNewChat();

    const afterNew = useStore.getState();
    expect(controller.signal.aborted).toBe(false);
    expect(afterNew.sessionId).not.toBe(originalSession);
    expect(afterNew.isChatLoading).toBe(false);

    afterNew.updateMessageInSession(originalSession, 'ai-1', {
      content: 'Final NVDA answer',
      isLoading: false,
    });

    useStore.getState().selectConversation(originalSession);
    const restored = useStore.getState();
    expect(restored.messages.some((message) => message.content === 'Final NVDA answer')).toBe(true);
    expect(restored.isChatLoading).toBe(true);

    restored.setSessionLoading(originalSession, false);
    expect(useStore.getState().isChatLoading).toBe(false);
  });

  it('restores execution status per conversation instead of leaking global progress', () => {
    const state = useStore.getState();
    const originalSession = state.sessionId;
    state.setSessionLoading(originalSession, true);
    state.setStatus('Streaming response...');
    state.setExecutionState('Searching news', 42);

    state.startNewChat();
    const nextSession = useStore.getState().sessionId;
    expect(nextSession).not.toBe(originalSession);
    expect(useStore.getState().statusMessage).toBeNull();
    expect(useStore.getState().currentStep).toBeNull();
    expect(useStore.getState().executionProgress).toBeNull();

    useStore.getState().selectConversation(originalSession);
    expect(useStore.getState().statusMessage).toBe('Streaming response...');
    expect(useStore.getState().currentStep).toBe('Searching news');
    expect(useStore.getState().executionProgress).toBe(42);

    useStore.getState().setSessionLoading(originalSession, false);
    expect(useStore.getState().statusMessage).toBeNull();
    expect(useStore.getState().currentStep).toBeNull();
    expect(useStore.getState().executionProgress).toBeNull();
  });

  it('keeps draft text isolated per conversation while switching', () => {
    const state = useStore.getState();
    const originalSession = state.sessionId;
    state.setDraft('分析这两张图 [Image #1] [Image #2]');

    state.startNewChat();
    const newSession = useStore.getState().sessionId;
    expect(newSession).not.toBe(originalSession);
    expect(useStore.getState().draft).toBe('');

    useStore.getState().setDraft('NVDA news');
    useStore.getState().selectConversation(originalSession);
    expect(useStore.getState().draft).toBe('分析这两张图 [Image #1] [Image #2]');

    useStore.getState().selectConversation(newSession);
    expect(useStore.getState().draft).toBe('NVDA news');
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
