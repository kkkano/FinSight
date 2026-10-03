import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { apiClient } from '../api/client';
import * as http from '../api/http';
import { zh } from '../locales/zh';
import { useStore } from './useStore';

const legacyRecoveryFixture = () => {
  const query = '分析一下 英特尔 的最新基本面、技术面、催化剂与主要风险';
  const prefix = Array.from({ length: 8 }, (_, index) => ({ id: `legacy-history-${index}`,
    role: index % 2 === 0 ? 'user' as const : 'assistant' as const,
    content: `Earlier saved turn ${index}`, timestamp: index + 1 }));
  const legacyUser = { id: 'legacy-question-id', role: 'user' as const, content: query, timestamp: 1000 };
  const canonicalUser = { id: 'canonical-question-id', role: 'user' as const, content: query,
    timestamp: 1000 + 9 * 3600000, run_id: 'saved-legacy-run' };
  const answer = { id: 'canonical-answer-id', role: 'assistant' as const, content: 'Recovered INTC canonical analysis',
    timestamp: canonicalUser.timestamp + 1, run_id: canonicalUser.run_id, reply_to: canonicalUser.id };
  return { prefix, legacyUser, canonicalUser, answer, backend: [...prefix, legacyUser, canonicalUser, answer] };
};

const openLegacyRecovery = async () => {
  const fixture = legacyRecoveryFixture();
  const state = useStore.getState();
  const sid = state.sessionId;
  useStore.setState({ messages: [] });
  for (const message of [...fixture.prefix, fixture.legacyUser]) state.addMessage(message);
  state.addMessage({ id: 'legacy-empty-answer', role: 'assistant', content: '', timestamp: 1001, isLoading: true });
  await state.flushConversationSync(sid);
  state.startNewChat();
  await state.flushConversationSync(useStore.getState().sessionId);
  vi.clearAllMocks();
  return { sid, fixture };
};

describe('useStore conversation lifecycle', () => {
  afterEach(() => {
    useStore.getState().setAuthIdentity(null);
    vi.restoreAllMocks();
  });

  beforeEach(async () => {
    vi.spyOn(http, 'buildAuthHeaders').mockResolvedValue({ Authorization: 'Bearer fixture-token' });
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
    state.setAuthIdentity(null);
    state.setAuthIdentity({ userId: 'test-user', email: null });
    state.setSessionId('public:test-user:default');
    state.clearConversationContext();
    await useStore.getState().flushConversationSync(useStore.getState().sessionId);
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
    await useStore.getState().flushConversationSync(useStore.getState().sessionId);
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

  it('restores an eleven-message legacy snapshot through its adjacent canonical reply without clock matching or remote writes', async () => {
    const { sid, fixture } = await openLegacyRecovery();
    expect(fixture.backend).toHaveLength(11);
    vi.mocked(apiClient.getConversation).mockResolvedValue({ success: true, session_id: sid,
      conversation: { messages: fixture.backend } });
    useStore.getState().selectConversation(sid);
    await Promise.resolve();
    await Promise.resolve();
    const restored = useStore.getState().messages;
    expect(restored).toHaveLength(10);
    expect(restored.at(-2)?.id).toBe(fixture.canonicalUser.id);
    expect(restored.at(-1)).toMatchObject({ id: fixture.answer.id, content: fixture.answer.content,
      runId: fixture.canonicalUser.run_id, replyTo: fixture.canonicalUser.id, isLoading: false });
    expect(restored.some((message) => message.id === fixture.legacyUser.id)).toBe(false);
    expect(apiClient.createConversation).not.toHaveBeenCalled();
  });

  it('restores thirteen legacy messages while retaining both genuinely repeated canonical research runs', async () => {
    const { sid, fixture } = await openLegacyRecovery();
    const repeatedUser = { ...fixture.canonicalUser, id: 'canonical-repeat-user', run_id: 'saved-repeat-run' };
    const repeatedAnswer = { ...fixture.answer, id: 'canonical-repeat-answer', content: 'Second saved INTC research answer',
      run_id: repeatedUser.run_id, reply_to: repeatedUser.id };
    const backend = [...fixture.backend, repeatedUser, repeatedAnswer];
    expect(backend).toHaveLength(13);
    vi.mocked(apiClient.getConversation).mockResolvedValue({ success: true, session_id: sid,
      conversation: { messages: backend } });
    useStore.getState().selectConversation(sid);
    await Promise.resolve();
    await Promise.resolve();
    const restored = useStore.getState().messages;
    expect(restored).toHaveLength(12);
    expect(restored.filter((message) => message.role === 'user' && message.content === fixture.legacyUser.content))
      .toHaveLength(2);
    expect(restored.some((message) => message.content === fixture.answer.content)).toBe(true);
    expect(restored.at(-1)).toMatchObject({ id: repeatedAnswer.id, content: repeatedAnswer.content,
      runId: repeatedUser.run_id, replyTo: repeatedUser.id });
    expect(restored.some((message) => message.id === fixture.legacyUser.id)).toBe(false);
    expect(apiClient.createConversation).not.toHaveBeenCalled();
  });

  it.each(['different-query', 'unbound-user', 'running-answer', 'error-answer', 'incomplete-tail'])('rejects a multi-run legacy tail with %s', async (reason) => {
    const { sid, fixture } = await openLegacyRecovery();
    const repeatedUser = { ...fixture.canonicalUser, id: 'repeat-user', run_id: 'repeat-run',
      ...(reason === 'different-query' ? { content: 'A different INTC question' } : {}),
      ...(reason === 'unbound-user' ? { run_id: '' } : {}) };
    const repeatedAnswer = { ...fixture.answer, id: 'repeat-answer', run_id: 'repeat-run', reply_to: repeatedUser.id,
      ...(reason === 'running-answer' ? { answer_status: 'running' } : {}),
      ...(reason === 'error-answer' ? { error: 'Incomplete research' } : {}) };
    vi.mocked(apiClient.getConversation).mockResolvedValue({ success: true, session_id: sid,
      conversation: { messages: [...fixture.backend, repeatedUser, ...(reason === 'incomplete-tail' ? [] : [repeatedAnswer])] } });
    useStore.getState().selectConversation(sid);
    await Promise.resolve();
    await Promise.resolve();
    expect(useStore.getState().messages.some((message) => message.id === fixture.answer.id)).toBe(false);
    expect(useStore.getState().messages.some((message) => message.id === fixture.legacyUser.id)).toBe(true);
    expect(apiClient.createConversation).not.toHaveBeenCalled();
  });

  it.each(['query', 'run', 'reply', 'bound-legacy', 'later-question', 'session'])('rejects an unsafe adjacent legacy recovery: %s', async (reason) => {
    const { sid, fixture } = await openLegacyRecovery();
    let backend: Array<Record<string, unknown>> = fixture.backend;
    if (reason === 'query') backend = [...fixture.prefix, fixture.legacyUser,
      { ...fixture.canonicalUser, content: 'A different INTC question' }, fixture.answer];
    if (reason === 'run') backend = [...fixture.prefix, fixture.legacyUser, fixture.canonicalUser,
      { ...fixture.answer, run_id: 'another-run' }];
    if (reason === 'reply') backend = [...fixture.prefix, fixture.legacyUser, fixture.canonicalUser,
      { ...fixture.answer, reply_to: fixture.legacyUser.id }];
    if (reason === 'bound-legacy') backend = [...fixture.prefix,
      { ...fixture.legacyUser, run_id: 'real-earlier-run' }, fixture.canonicalUser, fixture.answer];
    if (reason === 'later-question') backend = [...fixture.backend,
      { id: 'later-real-question', role: 'user', content: fixture.legacyUser.content, timestamp: 99999999 }];
    vi.mocked(apiClient.getConversation).mockResolvedValue({ success: true,
      session_id: reason === 'session' ? 'public:other-user:default' : sid, conversation: { messages: backend } });
    useStore.getState().selectConversation(sid);
    await Promise.resolve();
    await Promise.resolve();
    expect(useStore.getState().messages.some((message) => message.id === fixture.answer.id)).toBe(false);
    expect(useStore.getState().messages.some((message) => message.id === fixture.legacyUser.id)).toBe(true);
    expect(apiClient.createConversation).not.toHaveBeenCalled();
  });

  it.each(['new-message', 'new-owner'])('does not let late legacy hydration override %s', async (change) => {
    const { sid, fixture } = await openLegacyRecovery();
    let resolve: (value: Awaited<ReturnType<typeof apiClient.getConversation>>) => void = () => undefined;
    vi.mocked(apiClient.getConversation).mockReturnValue(new Promise((complete) => { resolve = complete; }));
    useStore.getState().selectConversation(sid);
    if (change === 'new-message') useStore.getState().addMessage({ id: 'new-local-question', role: 'user', content: 'New research request', timestamp: 2 });
    else useStore.getState().setAuthIdentity({ userId: 'another-user', email: null });
    resolve({ success: true, session_id: sid, conversation: { messages: fixture.backend } });
    await Promise.resolve();
    expect(useStore.getState().messages.some((message) => message.id === fixture.answer.id)).toBe(false);
    if (change === 'new-message') expect(useStore.getState().messages.at(-1)?.id).toBe('new-local-question');
    else expect(useStore.getState().authIdentity?.userId).toBe('another-user');
  });

  it('still saves the answer remotely when local storage fails', async () => {
    const setItem = vi.fn(() => { throw new Error('QuotaExceededError'); });
    vi.stubGlobal('window', { localStorage: { setItem, getItem: () => null } });
    try {
      useStore.getState().addMessage({ id: 'answer-without-storage', role: 'assistant', content: 'Answer survives quota', timestamp: 4 });
      await useStore.getState().flushConversationSync(useStore.getState().sessionId);
      expect(apiClient.createConversation).toHaveBeenCalledWith(useStore.getState().sessionId,
        expect.objectContaining({ messages: expect.arrayContaining([expect.objectContaining({ content: 'Answer survives quota' })]) }),
        expect.objectContaining({ signal: expect.any(AbortSignal) }));
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it('keeps the selected conversation on same-owner token and profile updates', () => {
    useStore.getState().selectConversation('public:test-user:selected-thread');
    useStore.getState().setAuthIdentity({ userId: 'test-user', email: 'updated@example.com' });
    expect(useStore.getState().sessionId).toBe('public:test-user:selected-thread');
  });

  it('restores the initial persisted thread only when its owner matches authenticated identity', () => {
    useStore.setState({ authIdentity: null, sessionId: 'public:test-user:saved-thread' });
    useStore.getState().setAuthIdentity({ userId: 'test-user', email: null });
    expect(useStore.getState().sessionId).toBe('public:test-user:saved-thread');
    useStore.setState({ authIdentity: null, sessionId: 'public:another-user:private-thread' });
    useStore.getState().setAuthIdentity({ userId: 'test-user', email: null });
    expect(useStore.getState().sessionId).toBe('public:test-user:default');
  });

  it('serializes snapshots and merges waiting updates before confirming final persistence', async () => {
    let releaseFirst: () => void = () => undefined;
    let savedMessages: Array<Record<string, unknown>> = [];
    vi.mocked(apiClient.createConversation).mockImplementationOnce((_sid, payload) => new Promise((resolve) => {
      releaseFirst = () => { savedMessages = payload?.messages || []; resolve({ success: true, session_id: _sid! }); };
    })).mockImplementation(async (sid, payload) => {
      savedMessages = payload?.messages || [];
      return { success: true, session_id: sid! };
    });
    const state = useStore.getState();
    const sid = state.sessionId;
    state.addMessage({ id: 'serial-user', role: 'user', content: 'INTC analysis', timestamp: 1 });
    await vi.waitFor(() => expect(apiClient.createConversation).toHaveBeenCalledOnce());
    state.addMessage({ id: 'serial-assistant', role: 'assistant', content: '', timestamp: 2, isLoading: true });
    state.updateMessageInSession(sid, 'serial-assistant', { content: 'Completed answer', isLoading: false });
    let confirmed = false;
    const completed = state.flushConversationSync(sid).then((saved) => { confirmed = saved; });
    await Promise.resolve();
    expect(confirmed).toBe(false);
    expect(apiClient.createConversation).toHaveBeenCalledOnce();
    releaseFirst();
    await completed;
    expect(apiClient.createConversation).toHaveBeenCalledTimes(2);
    expect(confirmed).toBe(true);
    expect(savedMessages.at(-1)).toMatchObject({ role: 'assistant', content: 'Completed answer' });
  });

  it('preserves completed local content when remote persistence rejects', async () => {
    vi.mocked(apiClient.createConversation).mockRejectedValueOnce(new Error('fixture network failure'));
    const state = useStore.getState();
    state.addMessage({ id: 'unsynced-answer', role: 'assistant', content: 'Generated answer remains', timestamp: 1 });
    expect(await state.flushConversationSync(state.sessionId)).toBe(false);
    expect(useStore.getState().messages.at(-1)?.content).toBe('Generated answer remains');
  });

  it('discards old-owner pending snapshots after asynchronous token lookup', async () => {
    let resolveHeaders: (headers: Record<string, string>) => void = () => undefined;
    vi.mocked(http.buildAuthHeaders).mockReturnValueOnce(new Promise((resolve) => { resolveHeaders = resolve; }));
    useStore.getState().addMessage({ id: 'old-owner', role: 'user', content: 'Private request', timestamp: 1 });
    await Promise.resolve();
    useStore.getState().setAuthIdentity({ userId: 'new-user', email: null });
    resolveHeaders({ Authorization: 'Bearer fixture-old-owner' });
    await Promise.resolve();
    await Promise.resolve();
    expect(apiClient.createConversation).not.toHaveBeenCalled();
  });

  it('aborts old-owner in-flight persistence and clears later queued snapshots on account change', async () => {
    let requestSignal: AbortSignal | undefined;
    let finish: () => void = () => undefined;
    vi.mocked(apiClient.createConversation).mockImplementation((_sid, _payload, options) => new Promise((resolve) => {
      requestSignal = options?.signal;
      finish = () => resolve({ success: true, session_id: _sid! });
    }));
    useStore.getState().addMessage({ id: 'queued-user', role: 'user', content: 'Old account', timestamp: 1 });
    await vi.waitFor(() => expect(apiClient.createConversation).toHaveBeenCalledOnce());
    useStore.getState().addMessage({ id: 'queued-answer', role: 'assistant', content: 'Old account answer', timestamp: 2 });
    useStore.getState().setAuthIdentity({ userId: 'new-user', email: null });
    expect(requestSignal?.aborted).toBe(true);
    finish();
    await Promise.resolve();
    await Promise.resolve();
    expect(apiClient.createConversation).toHaveBeenCalledOnce();
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

  it('recovers a lost assistant slot only for the still-owned run and matching question', () => {
    const state = useStore.getState();
    const sid = state.sessionId;
    const controller = new AbortController();
    state.addMessage({ id: 'owned-question', role: 'user', content: 'INTC research', timestamp: 1 });
    state.setSessionLoading(sid, true);
    state.setSessionAbortController(sid, controller);
    state.updateMessageInSession(sid, 'lost-answer', { content: 'Recovered canonical answer', isLoading: false }, {
      syncBackend: false, recovery: { ownerId: 'test-user', runId: 'owned-run', userMessageId: 'owned-question', controller, timestamp: 2 },
    });
    expect(useStore.getState().messages.at(-1)).toMatchObject({ id: 'lost-answer', content: 'Recovered canonical answer',
      runId: 'owned-run', replyTo: 'owned-question' });
  });

  it.each(['clear', 'delete', 'account', 'abort', 'question', 'other-run'])('never resurrects a revoked slot after %s', (reason) => {
    const state = useStore.getState();
    const sid = state.sessionId;
    const controller = new AbortController();
    state.addMessage({ id: 'revoked-question', role: 'user', content: 'INTC research', timestamp: 1 });
    state.setSessionLoading(sid, true);
    state.setSessionAbortController(sid, controller);
    if (reason === 'clear') state.clearConversationContext();
    if (reason === 'delete') state.deleteConversation(sid);
    if (reason === 'account') state.setAuthIdentity({ userId: 'other-user', email: null });
    if (reason === 'abort') controller.abort();
    if (reason === 'question') state.removeMessage('revoked-question');
    if (reason === 'other-run') state.addMessage({ id: 'new-answer', role: 'assistant', content: 'New run answer',
      timestamp: 2, runId: 'new-run', replyTo: 'revoked-question' });
    state.updateMessageInSession(sid, 'lost-answer', { content: 'Must not return', isLoading: false }, {
      syncBackend: false, recovery: { ownerId: 'test-user', runId: 'revoked-run', userMessageId: 'revoked-question', controller, timestamp: 3 },
    });
    expect(useStore.getState().messages.some((message) => message.content === 'Must not return')).toBe(false);
    expect(useStore.getState().conversationSummaries.some((summary) => summary.lastMessagePreview === 'Must not return')).toBe(false);
  });

  it('updates the same-run canonical slot without creating a duplicate', () => {
    const state = useStore.getState();
    const sid = state.sessionId;
    const controller = new AbortController();
    state.addMessage({ id: 'canonical-question', role: 'user', content: 'INTC research', timestamp: 1 });
    state.addMessage({ id: 'server-answer', role: 'assistant', content: 'Saved answer', timestamp: 2,
      runId: 'same-run', replyTo: 'canonical-question' });
    state.setSessionLoading(sid, true);
    state.setSessionAbortController(sid, controller);
    state.updateMessageInSession(sid, 'client-answer', { content: 'Canonical final text', isLoading: false }, {
      syncBackend: false, recovery: { ownerId: 'test-user', runId: 'same-run', userMessageId: 'canonical-question', controller, timestamp: 2 },
    });
    expect(useStore.getState().messages.filter((message) => message.replyTo === 'canonical-question')).toHaveLength(1);
    expect(useStore.getState().messages.at(-1)?.content).toBe('Canonical final text');
  });
});
