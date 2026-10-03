import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { apiClient } from '../api/client';
import { zh } from '../locales/zh';
import { useStore } from './useStore';

describe('useStore conversation lifecycle', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  beforeEach(() => {
    vi.spyOn(apiClient, 'createConversation').mockResolvedValue({
      success: true,
      session_id: 'public:test-user:default',
    });
    vi.spyOn(apiClient, 'getConversation').mockResolvedValue({
      success: true,
      session_id: 'public:test-user:default',
    });
    vi.spyOn(apiClient, 'deleteConversation').mockResolvedValue({
      success: true,
      session_id: 'public:test-user:default',
    });
    if (typeof window !== 'undefined') {
      window.localStorage.clear();
    }
    const state = useStore.getState();
    state.setAuthIdentity({ userId: 'test-user', email: null });
    state.setSessionId('public:test-user:default');
    state.clearConversationContext();
    vi.clearAllMocks();
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

  it('keeps anonymous sessions local without calling protected conversation APIs', async () => {
    const createConversation = vi.mocked(apiClient.createConversation);
    const getConversation = vi.mocked(apiClient.getConversation);

    useStore.getState().setAuthIdentity(null);
    useStore.getState().setSessionId('public:anonymous:test');
    await Promise.resolve();

    expect(createConversation).not.toHaveBeenCalled();
    expect(getConversation).not.toHaveBeenCalled();
  });

  it('does not trust a user-shaped session id without an authenticated identity', async () => {
    const createConversation = vi.mocked(apiClient.createConversation);
    const getConversation = vi.mocked(apiClient.getConversation);

    useStore.getState().setAuthIdentity(null);
    useStore.getState().setSessionId('public:stale-user:default');
    await Promise.resolve();

    expect(useStore.getState().sessionId).toMatch(/^public:anonymous:/);
    expect(createConversation).not.toHaveBeenCalled();
    expect(getConversation).not.toHaveBeenCalled();
  });

  it('does not treat an anonymous session from another tenant as local', async () => {
    const createConversation = vi.mocked(apiClient.createConversation);
    const getConversation = vi.mocked(apiClient.getConversation);

    useStore.getState().setAuthIdentity(null);
    useStore.getState().setSessionId('tenant:anonymous:default');
    await Promise.resolve();

    expect(useStore.getState().sessionId).toMatch(/^public:anonymous:/);
    expect(createConversation).not.toHaveBeenCalled();
    expect(getConversation).not.toHaveBeenCalled();
  });

  it('does not let an authenticated user select or sync another user session', async () => {
    const createConversation = vi.mocked(apiClient.createConversation);
    const getConversation = vi.mocked(apiClient.getConversation);
    const ownSessionId = useStore.getState().sessionId;

    useStore.getState().setSessionId('public:other-user:private');
    useStore.getState().selectConversation('public:other-user:private');
    await Promise.resolve();

    expect(useStore.getState().sessionId).toBe(ownSessionId);
    expect(createConversation).not.toHaveBeenCalledWith(
      'public:other-user:private',
      expect.anything(),
    );
    expect(getConversation).not.toHaveBeenCalledWith('public:other-user:private');
  });

  it('isolates local conversations and late stream updates when the account changes', () => {
    const aliceSessionId = useStore.getState().sessionId;
    const controller = new AbortController();
    useStore.getState().addMessage({
      id: 'alice-private',
      role: 'user',
      content: 'Alice private research',
      timestamp: 1,
    });
    useStore.getState().setSessionAbortController(aliceSessionId, controller);

    useStore.getState().setAuthIdentity({ userId: 'bob', email: null });

    const switched = useStore.getState();
    expect(controller.signal.aborted).toBe(true);
    expect(switched.sessionId).toBe('public:bob:default');
    expect(switched.messages).toHaveLength(1);
    expect(switched.messages[0].id).toBe('welcome');
    expect(switched.conversationSummaries.every((item) => item.sessionId.startsWith('public:bob:'))).toBe(true);

    switched.addMessageToSession(aliceSessionId, {
      id: 'late-alice-response',
      role: 'assistant',
      content: 'Late response',
      timestamp: 2,
    });
    expect(useStore.getState().conversationSummaries.some((item) => item.sessionId === aliceSessionId)).toBe(false);
  });

  it('reads an authenticated conversation without overwriting its saved history', async () => {
    const createConversation = vi.mocked(apiClient.createConversation);
    const getConversation = vi.mocked(apiClient.getConversation);

    useStore.getState().setSessionId('public:test-user:second');
    await Promise.resolve();

    expect(createConversation).not.toHaveBeenCalled();
    expect(getConversation).toHaveBeenCalledOnce();
  });

  it('shows interrupted empty assistant slots as retryable after reopening', () => {
    const sid = useStore.getState().sessionId;
    useStore.getState().addMessage({ id: 'pending-user', role: 'user', content: 'INTC research', timestamp: 1 });
    useStore.getState().addMessage({ id: 'pending-assistant', role: 'assistant', content: '', timestamp: 2, isLoading: true });
    useStore.getState().startNewChat();
    useStore.getState().selectConversation(sid);
    const answer = useStore.getState().messages.find((message) => message.id === 'pending-assistant');
    expect(answer).toMatchObject({ content: zh.chat.savedAnswerInterrupted, error: zh.chat.savedAnswerInterrupted,
      isLoading: false, canRetry: true });
  });

  it('restores a completed backend answer for a missing local reply', async () => {
    const sid = useStore.getState().sessionId;
    useStore.getState().addMessage({ id: 'research-user', role: 'user', content: 'INTC research', timestamp: 1 });
    useStore.getState().startNewChat();
    vi.mocked(apiClient.getConversation).mockResolvedValue({ success: true, session_id: sid, conversation: {
      messages: [{ id: 'research-user', role: 'user', content: 'INTC research', timestamp: 1 },
        { id: 'saved-answer', role: 'assistant', content: 'Verified INTC answer', timestamp: 2 }],
    } });
    vi.clearAllMocks();
    useStore.getState().selectConversation(sid);
    expect(useStore.getState().messages.at(-1)?.error).toBe(zh.chat.missingSavedAnswer);
    await Promise.resolve();
    await Promise.resolve();
    expect(useStore.getState().messages.at(-1)).toMatchObject({ content: 'Verified INTC answer', error: undefined, canRetry: false });
    expect(apiClient.createConversation).not.toHaveBeenCalled();
  });

  it('does not replace newly sent messages with late backend recovery', async () => {
    const sid = useStore.getState().sessionId;
    useStore.getState().addMessage({ id: 'research-user', role: 'user', content: 'INTC research', timestamp: 1 });
    useStore.getState().startNewChat();
    let resolve: (value: Awaited<ReturnType<typeof apiClient.getConversation>>) => void = () => undefined;
    vi.mocked(apiClient.getConversation).mockReturnValue(new Promise((complete) => { resolve = complete; }));
    useStore.getState().selectConversation(sid);
    useStore.getState().addMessage({ id: 'new-user', role: 'user', content: 'New question', timestamp: 3 });
    resolve({ success: true, session_id: sid, conversation: { messages: [
      { id: 'research-user', role: 'user', content: 'INTC research', timestamp: 1 },
      { id: 'saved-answer', role: 'assistant', content: 'Old recovered answer', timestamp: 2 },
    ] } });
    await Promise.resolve();
    expect(useStore.getState().messages.at(-1)?.id).toBe('new-user');
  });

  it('still saves the answer remotely when local storage fails', () => {
    const setItem = vi.fn(() => { throw new Error('QuotaExceededError'); });
    vi.stubGlobal('window', { localStorage: { setItem, getItem: () => null } });
    try {
      useStore.getState().addMessage({ id: 'answer-without-storage', role: 'assistant', content: 'Answer survives quota', timestamp: 4 });
      expect(apiClient.createConversation).toHaveBeenCalledWith(useStore.getState().sessionId,
        expect.objectContaining({ messages: expect.arrayContaining([expect.objectContaining({ content: 'Answer survives quota' })]) }));
    } finally {
      vi.unstubAllGlobals();
    }
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

  it('restores streamed partial content when returning to an in-flight conversation', () => {
    const state = useStore.getState();
    const originalSession = state.sessionId;

    state.addMessage({ id: 'user-stream', role: 'user', content: '今天 NVDA 有什么新闻', timestamp: 20 });
    state.addMessageToSession(originalSession, {
      id: 'ai-stream',
      role: 'assistant',
      content: '',
      timestamp: 21,
      isLoading: true,
    });
    state.setSessionLoading(originalSession, true);
    state.updateMessageInSession(originalSession, 'ai-stream', {
      content: 'NVDA 今天主要消息是',
      isLoading: true,
    });

    state.startNewChat();
    expect(useStore.getState().sessionId).not.toBe(originalSession);

    useStore.getState().selectConversation(originalSession);

    const restored = useStore.getState();
    const streamingMessage = restored.messages.find((message) => message.id === 'ai-stream');
    expect(streamingMessage?.content).toBe('NVDA 今天主要消息是');
    expect(streamingMessage?.isLoading).toBe(true);
    expect(restored.isChatLoading).toBe(true);
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
    state.setPendingChatHandoffContext(originalSession, {
      sessionId: originalSession,
      sourceView: 'dashboard',
      sourceTab: 'overview',
    });
    state.startNewChat();

    useStore.getState().deleteConversation(originalSession);

    const next = useStore.getState();
    expect(next.sessionId).not.toBe(originalSession);
    expect(next.conversationSummaries.some((item) => item.sessionId === originalSession)).toBe(false);
    expect(next.pendingChatHandoffContextBySession[originalSession]).toBeUndefined();
  });

  it('takes one-shot handoff context atomically and only from the matching session', () => {
    const state = useStore.getState();
    const firstSession = state.sessionId;
    const secondSession = 'public:test-user:second';
    state.setPendingChatHandoffContext(firstSession, {
      sessionId: firstSession,
      sourceView: 'dashboard',
      sourceTab: 'overview',
    });
    state.setPendingChatHandoffContext(firstSession, {
      sessionId: firstSession,
      sourceView: 'dashboard',
      sourceTab: 'technical',
    });
    state.setPendingChatHandoffContext(secondSession, {
      sessionId: secondSession,
      sourceView: 'command_palette',
    });

    expect(state.takePendingChatHandoffContext(firstSession)).toMatchObject({ sourceTab: 'technical' });
    expect(state.takePendingChatHandoffContext(firstSession)).toBeUndefined();
    expect(useStore.getState().pendingChatHandoffContextBySession[secondSession]).toMatchObject({
      sourceView: 'command_palette',
    });
  });

  it('ignores a late async message patch after its conversation was deleted', () => {
    const state = useStore.getState();
    const deletedSession = state.sessionId;
    state.addMessage({ id: 'user-late', role: 'user', content: 'AAPL 图表', timestamp: 10 });
    state.addMessageToSession(deletedSession, {
      id: 'ai-late',
      role: 'assistant',
      content: 'Final answer',
      timestamp: 11,
      isLoading: false,
    });
    state.startNewChat();

    useStore.getState().deleteConversation(deletedSession);
    useStore.getState().updateMessageInSession(deletedSession, 'ai-late', {
      content: 'Final answer\n\n[CHART:AAPL:line]',
    });

    const next = useStore.getState();
    expect(next.conversationSummaries.some((item) => item.sessionId === deletedSession)).toBe(false);
    if (typeof window !== 'undefined') {
      expect(window.localStorage.getItem(`finsight-messages:${deletedSession}`)).toBeNull();
    }
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
    expect(next.statusMessage).toBe(zh.chat.stopped);
    expect(next.currentStep).toBe(zh.chat.stoppedLabel);
    expect(next.executionProgress).toBe(40);
    expect(next.abortController).toBeNull();
  });
});
