import { Children, isValidElement, type ReactElement, type ReactNode } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ChatList } from '../ChatList';
import { ToastProvider } from '../ui/Toast';
import { ResearchReviewBlock } from './ResearchReview';
import { useChatStream } from '../../hooks/useChatStream';
import { useStore } from '../../store/useStore';
import { useDashboardStore } from '../../store/dashboardStore';
import type { Message } from '../../types';
import type { ResearchReview } from '../../types/runtime';
import * as http from '../../api/http';

vi.mock('react', async (importOriginal) => ({ ...await importOriginal<typeof import('react')>(),
  useCallback: (callback: unknown) => callback }));
vi.mock('../ui', () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock('../../store/useStore', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../store/useStore')>();
  return { ...actual, useStore: Object.assign((selector?: (state: ReturnType<typeof actual.useStore.getState>) => unknown) =>
    selector ? selector(actual.useStore.getState()) : actual.useStore.getState(), actual.useStore) };
});
vi.mock('../charts/EChart', () => ({ default: () => <div /> }));

const answer = 'AAPL 价格为 **10.25 美元**[1]。第二个数为 10.250。';
const review: ResearchReview = { status: 'completed', review_id: 'review-1', verdict: 'revise',
  findings: [{ quote: '**10.25 美元**[1]', issue: '价格与报价不符', evidence: '报价记录为 10.5 美元', suggestion: '更正价格' }],
  coverage: [{ requirement: '走势图', met: false }] };
const original: Message = { id: 'original-answer', runId: 'original-run', role: 'assistant', content: answer, timestamp: 2,
  blocks: [{ id: 'answer', kind: 'text', content: answer, revision: 0 }, { id: review.review_id, kind: 'review', review, revision: 1 }],
  evidence_pool: [{ source_id: '1', title: '报价', url: 'https://fixture.invalid/quote' }] };

function renderMessage(message: Message) {
  useStore.setState({ messages: [{ id: 'question', role: 'user', content: '请核对价格并画图', timestamp: 1 }, message] });
  return renderToStaticMarkup(<MemoryRouter><ToastProvider><ChatList /></ToastProvider></MemoryRouter>);
}

function findButton(node: ReactNode): ReactElement<{ onClick: () => Promise<void>; children?: ReactNode }> | undefined {
  if (!isValidElement<{ children?: ReactNode }>(node)) return undefined;
  if (node.type === 'button') return node as ReturnType<typeof findButton>;
  return Children.toArray(node.props.children).map(findButton).find(Boolean);
}

describe('只读核查显示与修订请求', () => {
  beforeEach(() => {
    useStore.getState().setAuthIdentity(null);
    useStore.getState().clearConversationContext();
    useStore.setState({ messages: [], isChatLoading: false, chatLoadingBySession: {}, abortControllersBySession: {} });
    useDashboardStore.setState({ activeAsset: null, activeSelections: [] });
  });
  afterEach(() => {
    useStore.getState().clearConversationContext();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('highlights only literal quote spans while preserving Markdown, citations, ticker links and stored text', () => {
    const markup = renderMessage(original);
    expect(markup).toContain('<mark');
    expect(markup).toContain('10.25 美元</mark>');
    expect(markup).toContain('href="#research-source-1"');
    expect(markup).toContain('/dashboard/AAPL');
    expect(markup).toContain('第二个数为 10.250。');
    expect(markup).toContain('按核查意见修订');
    expect(markup).toContain('尚未交付');
    expect(markup).toContain(`data-quote-offset="${answer.indexOf(review.findings![0].quote)}"`);
    expect(useStore.getState().messages.at(-1)?.content).toBe(answer);
    expect(useStore.getState().messages.at(-1)?.blocks).toEqual(original.blocks);
  });

  it('does not highlight a paraphrase or normalize whitespace to guess a location', () => {
    const changed = { ...review, findings: [{ ...review.findings![0], quote: '**10.25美元**[1]' }] };
    const markup = renderMessage({ ...original, blocks: [original.blocks![0], { id: changed.review_id, kind: 'review', review: changed, revision: 1 }] });
    expect(markup).not.toContain('<mark');
    expect(markup).toContain('data-quote-offset="-1"');
    expect(useStore.getState().messages.at(-1)?.content).toBe(answer);
  });

  it.each([
    [{ status: 'running', review_id: 'r' }, '正在核查回答…'],
    [{ status: 'completed', review_id: 'r', verdict: 'pass', findings: [], coverage: [] }, '已核查'],
    [{ status: 'completed', review_id: 'r', verdict: 'insufficient', findings: [], coverage: [] }, '资料不足以核实'],
    [{ status: 'unavailable', review_id: 'r', error_code: 'review_timeout' }, '核查超时，回答已保留。'],
  ] as const)('renders structured review state without replacing the answer', (value, expected) => {
    const markup = renderToStaticMarkup(<ResearchReviewBlock review={value as ResearchReview} answer={answer} />);
    expect(markup).toContain(expected);
    if (value.status === 'unavailable') {
      expect(markup).toContain('<details');
      expect(markup).not.toContain('已核查');
      expect(markup).not.toContain('资料不足以核实');
    }
  });

  it('retains prior report text and review under existing disclosure controls', () => {
    const revised = 'AAPL 价格为 10.5 美元[1]。';
    const nextReview: ResearchReview = { status: 'completed', review_id: 'review-2', supersedes_review_id: review.review_id,
      verdict: 'pass', findings: [], coverage: [] };
    const markup = renderMessage({ ...original, content: revised, blocks: [...original.blocks!,
      { id: 'answer-v2', kind: 'text', content: revised, revision: 1, revision_of: ['answer'], review_id: review.review_id },
      { id: nextReview.review_id, kind: 'review', review: nextReview, revision: 1 }] });
    expect(markup).toContain('修订前的回答');
    expect(markup).toContain('此前核查');
    expect(markup).toContain('10.25 美元');
    expect(markup).toContain('10.5 美元');
    expect(markup).toContain('已核查');
    expect(markup).not.toContain('按核查意见修订');
    expect(useStore.getState().messages.at(-1)?.blocks?.[0]).toEqual(original.blocks![0]);
  });

  it('links a cloud-restored revision to its original answer without needing a local request snapshot', () => {
    const markup = renderMessage({ ...original, id: 'revised-answer', reviewRevision: {
      source_message_id: 'prior-answer', source_run_id: 'prior-run', review_id: 'prior-review',
      answer: '原答案', findings: [], coverage: [],
    } });
    expect(markup).toContain('href="#message-prior-answer"');
    expect(markup).toContain('查看修订前的回答');
  });

  it('routes the revision button through the real chat sender and POST /api/execute with explicit review data', async () => {
    useStore.getState().addMessage({ id: 'question', role: 'user', content: '请核对价格并画图', timestamp: 1 });
    useStore.getState().addMessage(original);
    vi.spyOn(http, 'buildAuthHeaders').mockResolvedValue({});
    const posted = vi.fn(async (_url: string, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body));
      return new Response('data: ' + JSON.stringify({ type: 'done', response: '追加的修订答案', persistence_status: 'ephemeral', blocks: [] }) + '\n\n',
        { headers: { 'X-Run-Id': body.run_id } });
    });
    vi.stubGlobal('fetch', posted);
    const chat = useChatStream(useStore.getState().sessionId);
    const element = ResearchReviewBlock({ review, answer, onRevise: () => chat.revise(original.id, review.review_id) });
    const button = findButton(element);
    expect(button).toBeDefined();
    await button!.props.onClick();
    expect(posted).toHaveBeenCalledTimes(1);
    const [url, init] = posted.mock.calls[0];
    expect(url).toContain('/api/execute');
    expect(init?.method).toBe('POST');
    const body = JSON.parse(String(init?.body));
    expect(body.query).toBe('按核查意见修订');
    expect(body.resume_from_run_id).toBe(original.runId);
    expect(body.review_revision).toEqual({ source_message_id: original.id, source_run_id: original.runId,
      review_id: review.review_id, answer, findings: review.findings, coverage: review.coverage });
    expect(body.client_assistant_message_id).not.toBe(original.id);
    expect(useStore.getState().messages.find((message) => message.id === original.id)?.content).toBe(answer);
    expect(useStore.getState().messages.at(-1)?.content).toBe('追加的修订答案');
  });
});
