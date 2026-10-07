import { readFileSync } from 'node:fs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { apiClient } from '../api/client';
import type { SendMessageBody } from '../api/client';
import { useDashboardStore } from '../store/dashboardStore';
import { useStore } from '../store/useStore';
import type { Message, ReportIR } from '../types';
import { findRetryQuery, hasChatOutput, useChatStream } from './useChatStream';

vi.mock('react', async (importOriginal) => ({
  ...await importOriginal<typeof import('react')>(),
  useCallback: (callback: unknown) => callback,
}));
vi.mock('../components/ui', () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock('../utils/chartIntent', () => ({
  shouldGenerateChart: vi.fn(async () => ({ tickers: [], chartType: null })),
  injectChartMarkers: (content: string) => content,
}));

const messages: Message[] = [
  { id: 'u1', role: 'user', content: 'AAPL first', timestamp: 1 },
  { id: 'a1', role: 'assistant', content: 'first answer', timestamp: 2 },
  { id: 'u2', role: 'user', content: 'NVDA second', timestamp: 3 },
  { id: 'a2', role: 'assistant', content: 'second answer', timestamp: 4 },
];

describe('findRetryQuery', () => {
  it('为 assistant 重试复用它前面的最近一条 user query', () => {
    expect(findRetryQuery(messages, 'a1')).toBe('AAPL first');
    expect(findRetryQuery(messages, 'a2')).toBe('NVDA second');
  });

  it('目标消息不存在时不猜测 query', () => {
    expect(findRetryQuery(messages, 'missing')).toBeNull();
  });
});

describe('chat completion output contract', () => {
  it.each(['', '   ', '[object Object]'])('rejects empty or invalid completion %j', (content) => {
    expect(hasChatOutput(content)).toBe(false);
  });

  it('accepts real text or report content', () => {
    expect(hasChatOutput('有效分析')).toBe(true);
    expect(hasChatOutput('', { summary: '报告摘要' })).toBe(true);
    expect(hasChatOutput('', { synthesis_report: '完整研究报告' })).toBe(true);
    expect(hasChatOutput('', { summary: '', sections: [] })).toBe(false);
  });
});

describe('SSE 异步终态竞态契约', () => {
  it('主聊天在流返回后等待 onError 的异步恢复逻辑', () => {
    const source = readFileSync(new URL('./useChatStream.ts', import.meta.url), 'utf8');

    expect(source).toContain('terminalHandlingPromise =');
    expect(source).toContain('const pendingTerminalHandling = terminalHandlingPromise;');
    expect(source).toContain('if (pendingTerminalHandling) await pendingTerminalHandling;');
  });
});

describe('chat retry and recovery', () => {
  const oldReport = { summary: 'Previous report', ticker: '002174.SZ', sections: [] } as unknown as ReportIR;

  beforeEach(() => {
    vi.spyOn(apiClient, 'createConversation').mockImplementation(async (sessionId) => ({ success: true, session_id: sessionId! }));
    vi.spyOn(apiClient, 'getConversation').mockImplementation(async (sessionId) => ({ success: true, session_id: sessionId! }));
    useStore.getState().setAuthIdentity(null);
    useStore.getState().clearConversationContext();
    useStore.setState({ messages: [], currentTicker: null, isChatLoading: false, chatLoadingBySession: {}, abortControllersBySession: {} });
    useDashboardStore.setState({ activeAsset: null, activeSelections: [] });
  });

  afterEach(() => {
    useStore.getState().clearConversationContext();
    useStore.getState().setAuthIdentity(null);
    vi.restoreAllMocks();
  });

  it('retries the saved report request after dashboard changes and clears all old output before a failure', async () => {
    const selection = { type: 'filing' as const, id: 'original-filing', title: 'Original filing' };
    useDashboardStore.setState({
      activeAsset: { symbol: '002174.SZ', type: 'equity', display_name: '游族网络' },
      activeSelections: [selection],
    });
    useStore.getState().addMessage({ id: 'history-user', role: 'user', content: 'Earlier question', timestamp: 1 });
    useStore.getState().addMessage({ id: 'history-answer', role: 'assistant', content: 'Earlier answer', timestamp: 2 });
    const send = vi.spyOn(apiClient, 'sendMessageStream').mockImplementationOnce(async (_request, callbacks) => {
      callbacks.onDone?.(oldReport, [], { response: oldReport.summary, persistence_status: 'ephemeral' });
    });
    const sessionId = useStore.getState().sessionId;
    await useChatStream(sessionId).send('分析这份公告并生成报告', { outputMode: 'investment_report' });
    const originalRequest = send.mock.calls[0][0];
    const answer = useStore.getState().messages.at(-1)!;
    useStore.getState().updateMessage(answer.id, {
      evidence_pool: [{ title: 'Old source' }] as Message['evidence_pool'],
      thinking: [{ stage: 'old', message: 'Old thinking', timestamp: 'old' }],
      data_origin: 'LLM', as_of: 'old', fallback_used: true, tried_sources: ['old'], responseTime: 120,
    });
    // 请求快照必须经本地会话恢复后仍然可用。
    useStore.getState().startNewChat();
    useStore.getState().selectConversation(sessionId);
    selection.title = 'Mutated dashboard filing';
    useDashboardStore.setState({
      activeAsset: { symbol: 'AAPL', type: 'equity', display_name: 'Apple' },
      activeSelections: [{ type: 'news', id: 'new-news', title: 'New news' }],
    });
    useStore.getState().addMessage({ id: 'later-user', role: 'user', content: 'Later question', timestamp: 3 });
    let retrying: Message | undefined;
    send.mockImplementationOnce(async (request) => {
      retrying = useStore.getState().messages.find((message) => message.id === request.client_assistant_message_id);
      throw new Error('Retry fails');
    });

    await useChatStream(sessionId).retry(answer.id);

    const retryRequest = send.mock.calls[1][0];
    expect(retrying).toBeDefined();
    for (const field of ['report', 'evidence_pool', 'thinking', 'responseTime', 'data_origin', 'as_of', 'fallback_used', 'tried_sources'] as const) {
      expect(retrying?.[field]).toBeUndefined();
    }
    expect(retrying?.content).toBe('');
    expect(retryRequest.query).toBe(originalRequest.query);
    expect(retryRequest.options?.output_mode).toBe('investment_report');
    expect(retryRequest.context).toEqual({ active_symbol: '002174.SZ', view: 'chat', selection: {
      type: 'filing', id: 'original-filing', title: 'Original filing',
    } });
    expect(retryRequest.history).toEqual(originalRequest.history);
    expect(retryRequest.history?.map((message) => message.content)).toEqual(['Earlier question', 'Earlier answer']);
    expect(retryRequest.run_id).not.toBe(originalRequest.run_id);
    expect(retryRequest.client_user_message_id).toBe(originalRequest.client_user_message_id);
    const failed = useStore.getState().messages.find((message) => message.id === retryRequest.client_assistant_message_id)!;
    expect(failed.canRetry).toBe(true);
    expect(failed.error).toBeTruthy();
    expect(failed.report).toBeUndefined();
  });

  it.each(['unavailable', 'wrong-run', 'wrong-question'])('never recovers the latest session report when run recovery is %s', async (failure) => {
    useStore.getState().setAuthIdentity({ userId: 'retry-test-user', email: null });
    useStore.setState({ messages: [] });
    let request: SendMessageBody;
    const recover = vi.spyOn(apiClient, 'getExecutionRun').mockImplementation(async () => {
      if (failure === 'unavailable') throw new Error('Run unavailable');
      return { run_id: failure === 'wrong-run' ? 'previous-run' : request.run_id!, session_id: request.session_id!,
        user_message_id: failure === 'wrong-question' ? 'previous-user' : request.client_user_message_id!,
        assistant_message_id: request.client_assistant_message_id!, status: 'completed',
        result: { type: 'done', report: oldReport, response: 'Wrong recovered answer' } };
    });
    const latest = vi.spyOn(apiClient, 'listReportIndex');
    const replay = vi.spyOn(apiClient, 'getReportReplay');
    vi.spyOn(apiClient, 'sendMessageStream').mockImplementation(async (body, callbacks) => {
      request = body;
      callbacks.onError?.('Stream interrupted');
    });

    await useChatStream(useStore.getState().sessionId).send('请给我一份游族网络的投研分析报告');

    expect(recover).toHaveBeenCalledOnce();
    expect(latest).not.toHaveBeenCalled();
    expect(replay).not.toHaveBeenCalled();
    expect(useStore.getState().messages.at(-1)).toMatchObject({ error: 'Stream interrupted', canRetry: true });
    expect(useStore.getState().messages.at(-1)?.report).toBeUndefined();
  });

  it('recovers the completed result for the same run and question after a stream interruption', async () => {
    useStore.getState().setAuthIdentity({ userId: 'retry-test-user', email: null });
    useStore.setState({ messages: [] });
    let request: SendMessageBody;
    vi.spyOn(apiClient, 'getExecutionRun').mockImplementation(async (runId) => ({
      run_id: runId, session_id: request.session_id!, user_message_id: request.client_user_message_id!,
      assistant_message_id: request.client_assistant_message_id!, status: 'completed',
      result: { type: 'done', report: oldReport, response: 'Current recovered answer', persistence_status: 'saved' },
    }));
    vi.spyOn(apiClient, 'sendMessageStream').mockImplementation(async (body, callbacks) => {
      request = body;
      callbacks.onError?.('Stream interrupted');
    });

    await useChatStream(useStore.getState().sessionId).send('请给我一份游族网络的投研分析报告');

    expect(useStore.getState().messages.at(-1)).toMatchObject({ content: 'Current recovered answer', report: oldReport, isLoading: false });
    expect(useStore.getState().messages.at(-1)?.error).toBeUndefined();
  });
});
