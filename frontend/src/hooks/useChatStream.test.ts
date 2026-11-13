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

  it('publishes the exact answer before review and stores replayed review blocks without rewriting it', async () => {
    const answer = '原值 10.25  美元；[1]\n不追加图表标记。';
    const review = { status: 'completed', review_id: 'review-1', verdict: 'revise', findings: [
      { quote: '10.25', issue: '需核对价格', evidence: '报价记录', suggestion: '确认价格' },
    ], coverage: [{ requirement: '图表', met: false }] };
    const chart = await import('../utils/chartIntent');
    vi.mocked(chart.shouldGenerateChart).mockClear();
    vi.spyOn(apiClient, 'sendMessageStream').mockImplementation(async (body, callbacks) => {
      const emit = (seq: number, type: string, payload: Record<string, unknown>) => callbacks.onRuntimeEvent?.({
        schema_version: 2, type, run_id: body.run_id, session_id: body.session_id, seq, payload,
      });
      emit(1, 'content.delta', { block_id: 'answer', delta: answer });
      emit(2, 'answer.completed', { status: 'completed', review_pending: true });
      expect(useStore.getState().messages.at(-1)).toMatchObject({ content: answer, isLoading: false, answerStatus: 'complete' });
      emit(3, 'review.started', { status: 'running', review_id: 'review-1' });
      emit(4, 'review.finished', review);
      emit(4, 'review.finished', review);
      await new Promise((resolve) => setTimeout(resolve, 50));
      const duringReview = useStore.getState().messages.at(-1)!;
      expect(duringReview.content).toBe(answer);
      expect(duringReview.isLoading).toBe(false);
      expect(duringReview.blocks?.filter((block) => block.kind === 'review')).toHaveLength(1);
      callbacks.onDone?.(undefined, [], { response: answer, persistence_status: 'ephemeral' });
    });
    await useChatStream(useStore.getState().sessionId).send('请画走势图并说明价格');
    expect(useStore.getState().messages.at(-1)?.content).toBe(answer);
    expect(chart.shouldGenerateChart).not.toHaveBeenCalled();
  });

  it('sends an explicit review revision as a new message and preserves the original report and request relationship', async () => {
    const review = { status: 'completed' as const, review_id: 'review-1', verdict: 'revise' as const,
      findings: [{ quote: '旧价格', issue: '需更正', evidence: '原始报价', suggestion: '更正价格' }], coverage: [] };
    const original: Message = { id: 'original-answer', role: 'assistant', content: '旧价格 10.25', timestamp: 2,
      runId: 'original-run', runStatus: 'completed', report: oldReport,
      blocks: [{ id: 'answer', kind: 'text', content: '旧价格 10.25', revision: 0 }, { id: review.review_id, kind: 'review', review, revision: 1 }] };
    useStore.getState().addMessage({ id: 'original-question', role: 'user', content: '写一份报告', timestamp: 1 });
    useStore.getState().addMessage(original);
    const sent = vi.spyOn(apiClient, 'sendMessageStream').mockImplementation(async (_request, callbacks) => {
      callbacks.onDone?.(undefined, [], { response: '修订版价格 10.5', persistence_status: 'ephemeral', blocks: [] });
    });
    await useChatStream(useStore.getState().sessionId).revise(original.id, review.review_id);
    expect(sent).toHaveBeenCalledTimes(1);
    const body = sent.mock.calls[0][0];
    expect(body).toMatchObject({ query: '按核查意见修订', resume_from_run_id: original.runId,
      options: { output_mode: 'investment_report' }, review_revision: {
        source_message_id: original.id, source_run_id: original.runId, review_id: review.review_id,
        answer: original.content, findings: review.findings, coverage: review.coverage,
      } });
    expect(body.client_assistant_message_id).not.toBe(original.id);
    expect(useStore.getState().messages.find((message) => message.id === original.id)).toMatchObject(original);
    expect(useStore.getState().messages.at(-1)?.requestSnapshot?.reviewRevision).toEqual(body.review_revision);
  });

  it('sends strict account preferences and structured dashboard context without granting reference access', async () => {
    const state=useStore.getState(); state.setAuthIdentity({userId:'context-owner',email:null});
    const session=useStore.getState().sessionId;
    state.setPendingChatHandoffContext(session,{sessionId:session,sourceView:'dashboard',sourceTab:'overview',
      selectedMetric:{id:'trailing_pe',label:'市盈率',value:25,unit:null},timeRange:{start:'2026-10-01',end:'2026-10-31'},dataRefs:['existing-reference']});
    const sent=vi.spyOn(apiClient,'sendMessageStream').mockImplementation(async (_request,callbacks)=>{
      callbacks.onDone?.(undefined,[],{response:'上下文已接收',persistence_status:'ephemeral'});
    });
    await useChatStream(session).send('分析当前指标');
    expect(sent.mock.calls[0][0].context).toMatchObject({selected_metric:{id:'trailing_pe',value:25},
      time_range:{start:'2026-10-01',end:'2026-10-31'},data_refs:['existing-reference'],watchlist_auto_confirm:false,show_provider_reasoning:false});
    expect(sent.mock.calls[0][0].show_provider_reasoning).toBe(false);
    state.setWatchlistAutoConfirm(true); state.setShowProviderReasoning(true);
    await useChatStream(session).send('再看一次');
    expect(sent.mock.calls[1][0].context).toMatchObject({watchlist_auto_confirm:true,show_provider_reasoning:true});
    state.setAuthIdentity({userId:'other-owner',email:null});
    await useChatStream(useStore.getState().sessionId).send('新账号问题');
    expect(sent.mock.calls[2][0].context).toMatchObject({watchlist_auto_confirm:false,show_provider_reasoning:false});
    expect(sent.mock.calls[2][0].context?.data_refs).toBeUndefined();
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
    }, show_provider_reasoning:false,watchlist_auto_confirm:false });
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
    expect(useStore.getState().messages.at(-1)).toMatchObject({ error: '研究没有完成，生成的内容已保留。 请稍后重试。', canRetry: true });
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
  it('preserves body and blocks but marks persistence_failed delivery as failed', async () => {
    const blocks = [{ id: 'answer', kind: 'text', content: '已生成但未保存', revision: 0 }];
    vi.spyOn(apiClient, 'sendMessageStream').mockImplementation(async (_request, callbacks) => {
      callbacks.onDone?.(oldReport, [], { success: false, run_status: 'persistence_failed',
        persistence_status: 'failed', answer_status: 'partial', response: '已生成但未保存', blocks });
    });
    await useChatStream(useStore.getState().sessionId).send('AAPL 研究');
    const answer = useStore.getState().messages.at(-1)!;
    expect(answer).toMatchObject({ content: '已生成但未保存', blocks, isLoading: false,
      runStatus: 'persistence_failed', error: '回答已生成，但未保存成功。', canRetry: true });
    expect(answer.thinking?.at(-1)?.stage).toBe('error');
    expect(answer.report).toBeUndefined();
  });

  it('uses an error envelope response and artifact blocks without losing the received result', async () => {
    const blocks = [{ id: 'answer', kind: 'text', content: '部分研究结果', revision: 0 }];
    vi.spyOn(apiClient, 'sendMessageStream').mockImplementation(async (_request, callbacks) => {
      callbacks.onError?.('来源请求失败', { response: '部分研究结果', blocks, run_status: 'failed' });
    });
    await useChatStream(useStore.getState().sessionId).send('AAPL 研究');
    expect(useStore.getState().messages.at(-1)).toMatchObject({ content: '部分研究结果', blocks,
      isLoading: false, runStatus: 'failed', error: '研究没有完成，生成的内容已保留。 请稍后重试。' });
  });

  it('shows the safe failure reason and next action instead of the generic run message', async () => {
    vi.spyOn(apiClient, 'sendMessageStream').mockImplementation(async (_request, callbacks) => {
      callbacks.onError?.('本轮研究未完成，已保留可用内容。', { run_status: 'failed', error_code: 'model_timeout',
        reason: '模型在生成研究结论时超时。', recovery_action: '可从已有资料继续研究。' });
    });
    await useChatStream(useStore.getState().sessionId).send('AAPL 研究');
    expect(useStore.getState().messages.at(-1)).toMatchObject({ content: '模型响应超时，研究已中断。 请稍后重试。',
      error: '模型响应超时，研究已中断。 请稍后重试。', isLoading: false, runStatus: 'failed' });
  });

  it('maps old error codes when an authoritative failed delivery has only a generic message', async () => {
    vi.spyOn(apiClient, 'sendMessageStream').mockImplementation(async (_request, callbacks) => {
      callbacks.onDone?.(undefined, [], { run_status: 'failed', response: '已取得部分资料',
        error_code: 'agent_turn_budget_exhausted', message: '本轮研究未完成，已保留可用内容。', persistence_status: 'ephemeral' });
    });
    await useChatStream(useStore.getState().sessionId).send('AAPL 研究');
    expect(useStore.getState().messages.at(-1)).toMatchObject({ content: '已取得部分资料', runStatus: 'failed',
      error: '这次研究已达到步骤上限，还没完成。 请缩小研究范围或继续追问。', isLoading: false });
  });

  it('finishes completed research with evidence gaps without labelling it an execution error', async () => {
    vi.spyOn(apiClient, 'sendMessageStream').mockImplementation(async (_request, callbacks) => {
      callbacks.onDone?.(undefined, [], { success: true, run_status: 'completed', answer_status: 'partial',
        quality: { reasons: [{ code: 'partial_tool_failure', message: '盈利预期数据未取得。' }] },
        response: '已有行情结论；盈利预期缺失。', persistence_status: 'ephemeral' });
    });
    await useChatStream(useStore.getState().sessionId).send('AAPL 研究');
    const answer = useStore.getState().messages.at(-1)!;
    expect(answer).toMatchObject({ runStatus: 'completed', answerStatus: 'partial', isLoading: false, canRetry: true });
    expect(answer.error).toBeUndefined();
    expect(answer.thinking?.at(-1)).toMatchObject({ stage: 'done', message: '盈利预期数据未取得。', result: { status: 'partial' } });
  });

  it.each(['error', 'request-rejected'])('restores the assistant slot on %s when the current user turn remains', async (mode) => {
    vi.spyOn(apiClient, 'sendMessageStream').mockImplementation(async (_request, callbacks) => {
      useStore.setState((state) => ({ messages: state.messages.filter((message) => message.role === 'user') }));
      if (mode === 'request-rejected') throw new Error('request failed');
      callbacks.onError?.('模型服务连接中断。', { error_code: 'model_connection_error' });
    });
    await useChatStream(useStore.getState().sessionId).send('继续上一轮研究');
    const messages = useStore.getState().messages;
    expect(messages).toHaveLength(2);
    expect(messages[1]).toMatchObject({ role: 'assistant', isLoading: false, runStatus: 'failed', replyTo: messages[0].id });
    expect(messages[1].error).toBeTruthy();
    expect(useStore.getState().isChatLoading).toBe(false);
  });

  it('sends explicit recovery metadata only for a failed turn retry, never for an ordinary follow-up', async () => {
    const session = useStore.getState().sessionId;
    const sent = vi.spyOn(apiClient, 'sendMessageStream').mockImplementation(async (_request, callbacks) => {
      callbacks.onDone?.(undefined, [], { response: '补充研究结果', persistence_status: 'ephemeral' });
    });
    await useChatStream(session).send('研究 AAPL');
    const failed = useStore.getState().messages.at(-1)!;
    useStore.getState().updateMessage(failed.id, { runStatus: 'failed', error: '模型响应超时。' });
    await useChatStream(session).retry(failed.id);
    expect(sent.mock.calls[1][0].resume_from_run_id).toBe(failed.runId);
    expect(sent.mock.calls[1][0].query).toBe('研究 AAPL');
    expect(useStore.getState().messages.filter((message) => message.role === 'user')).toHaveLength(1);
    await useChatStream(session).send('那现金流呢');
    expect(sent.mock.calls[2][0].resume_from_run_id).toBeUndefined();
    expect(sent.mock.calls[2][0].query).toBe('那现金流呢');
  });

  it('keeps chosen skill IDs on retry and does not carry them into the next question', async () => {
    const session = useStore.getState().sessionId;
    const sent = vi.spyOn(apiClient, 'sendMessageStream').mockImplementation(async (_request, callbacks) => {
      callbacks.onDone?.(undefined, [], { response: '研究结果', persistence_status: 'ephemeral' });
    });
    await useChatStream(session).send('分析 AAPL 成长质量', { skillIds: ['growth-quality', 'growth-quality', 'ma-trend'] });
    const answer = useStore.getState().messages.at(-1)!;
    expect(sent.mock.calls[0][0].skill_ids).toEqual(['growth-quality', 'ma-trend']);
    await useChatStream(session).retry(answer.id);
    expect(sent.mock.calls[1][0].skill_ids).toEqual(['growth-quality', 'ma-trend']);
    expect(sent.mock.calls[1][0].resume_from_run_id).toBeUndefined();
    await useChatStream(session).send('解释市盈率');
    expect(sent.mock.calls[2][0].skill_ids).toBeUndefined();
  });

  it('requests supplied reasoning only after account opt-in and retains it in the owning message blocks', async () => {
    useStore.getState().setAuthIdentity({userId:'reasoning-owner',email:null});
    useStore.getState().setShowProviderReasoning(true);
    const sent = vi.spyOn(apiClient, 'sendMessageStream').mockImplementation(async (request, callbacks) => {
      callbacks.onRuntimeEvent?.({ type: 'reasoning.delta', run_id: request.run_id, session_id: request.session_id, seq: 1,
        payload: { kind: 'provider_raw', block_id: 'root_reasoning_1', delta: '核对价格与资料时点。', agent_id: 'root' } });
      callbacks.onDone?.(undefined, [], { response: '已完成核查。', persistence_status: 'ephemeral' });
    });
    await useChatStream(useStore.getState().sessionId).send('分析 AAPL');
    expect(sent.mock.calls[0][0].show_provider_reasoning).toBe(true);
    expect(useStore.getState().messages.at(-1)?.blocks).toContainEqual(expect.objectContaining({ kind: 'reasoning', reasoning_kind: 'provider_raw',
      id: 'root_reasoning_1', content: '核对价格与资料时点。' }));
  });
  it('keeps progress out of the final answer and the next request history', async () => {
    const sent = vi.spyOn(apiClient, 'sendMessageStream').mockImplementation(async (request, callbacks) => {
      const emit = (seq: number, type: string, payload: Record<string, unknown>) => callbacks.onRuntimeEvent?.({
        seq, type, payload, run_id: request.run_id, session_id: request.session_id,
      });
      emit(1, 'content.delta', { block_id: 'intro', delta: '我先查看现金流。' });
      emit(2, 'content.block_finished', { block_id: 'intro', content_phase: 'progress' });
      emit(3, 'content.delta', { block_id: 'final', delta: '正式结论。' });
      emit(4, 'content.block_finished', { block_id: 'final', content_phase: 'answer' });
      callbacks.onDone?.(undefined, [], { response: '正式结论。', persistence_status: 'ephemeral' });
    });
    const session = useStore.getState().sessionId;
    await useChatStream(session).send('分析 AAPL');
    const answer = useStore.getState().messages.at(-1)!;
    expect(answer.content).toBe('正式结论。');
    expect(answer.blocks?.[0]).toMatchObject({ content: '我先查看现金流。', content_phase: 'progress' });
    await useChatStream(session).send('再看收入');
    expect(sent.mock.calls[1][0].history?.filter((message) => message.role === 'assistant')).toEqual([{ role: 'assistant', content: '正式结论。' }]);
  });

  it.each(['/', '/growth-quality', '研究 AAPL /成长'])('does not send an unresolved skill command %s as a user question', async (query) => {
    const sent = vi.spyOn(apiClient, 'sendMessageStream');
    await useChatStream(useStore.getState().sessionId).send(query);
    expect(sent).not.toHaveBeenCalled();
    expect(useStore.getState().messages).toHaveLength(0);
  });

  it('sends PNG bytes only in the current request and never persists them in message snapshots', async () => {
    const image = { data_url: 'data:image/png;base64,TEST-TRANSIENT-IMAGE', name: '参考.png' };
    const sent = vi.spyOn(apiClient, 'sendMessageStream').mockImplementation(async (_request, callbacks) => {
      callbacks.onDone?.(undefined, [], { response: '图像分析结果', persistence_status: 'ephemeral' });
    });
    const session = useStore.getState().sessionId;
    await useChatStream(session).send('分析这张图', { images: [image] });
    expect(sent.mock.calls[0][0].images).toEqual([image]);
    const answer = useStore.getState().messages.at(-1)!;
    expect(answer.requestSnapshot?.hasTransientImages).toBe(true);
    expect(JSON.stringify(useStore.getState().messages)).not.toContain('TEST-TRANSIENT-IMAGE');
    expect(JSON.stringify(answer.requestSnapshot)).not.toContain('data:image/');
    await useChatStream(session).retry(answer.id);
    expect(sent).toHaveBeenCalledTimes(1);
    expect(useStore.getState().draft).toBe('分析这张图');
    await useChatStream(session).send('下一轮纯文本');
    expect(sent.mock.calls[1][0].images).toBeUndefined();
    expect(sent.mock.calls[1][0].history?.every((item) => !item.content.includes('data:image/'))).toBe(true);
  });

});
