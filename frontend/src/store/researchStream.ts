import { create } from 'zustand';
import type { ResearchBlock, ResearchReview, ResearchStreamState, RuntimeEvent } from '../types/runtime';

export const emptyResearchStream = (runId?: string): ResearchStreamState => ({ runId, seq: -1, blocks: [] });

const stringValue = (value: unknown): string => typeof value === 'string' ? value : '';

/** 仅校验事件结构；核查语义与原文定位均不靠关键词推断。 */
export function isResearchReview(value: unknown): value is ResearchReview {
  if (!value || typeof value !== 'object') return false;
  const review = value as ResearchReview;
  if (typeof review.review_id !== 'string' || !review.review_id
      || !['running', 'completed', 'unavailable'].includes(review.status)) return false;
  if (review.status !== 'completed') return true;
  return ['pass', 'revise', 'insufficient'].includes(review.verdict ?? '')
    && Array.isArray(review.findings) && review.findings.every((finding) => finding && typeof finding.quote === 'string'
      && finding.quote.length > 0 && typeof finding.issue === 'string' && typeof finding.evidence === 'string' && typeof finding.suggestion === 'string')
    && Array.isArray(review.coverage) && review.coverage.every((item) => item && typeof item.requirement === 'string' && typeof item.met === 'boolean');
}

export { researchFailure, researchFailureMessage } from '../utils/researchFailure';

export function researchQualityMessage(meta?: Record<string, unknown>): string {
  const reasons = [meta?.quality, meta?.report_quality].flatMap((quality) => quality && typeof quality === 'object'
    && Array.isArray((quality as Record<string, unknown>).reasons) ? (quality as { reasons: unknown[] }).reasons : []);
  return [...new Set(reasons.map((reason) => reason && typeof reason === 'object'
    ? stringValue((reason as Record<string, unknown>).message) : '').filter(Boolean))].join(' ')
    || '回答已生成，但部分信息还无法确认。';
}

export function normalizeRuntimeEvent(data: Record<string, unknown>): RuntimeEvent | null {
  const originalType = stringValue(data.type);
  const runtimeType = stringValue(data.runtime_type);
  if (String(data.schema_version) !== '2' && !originalType.includes('.')) return null;
  const type = runtimeType || (originalType === 'token' ? 'content.delta' : originalType);
  const payload = data.payload && typeof data.payload === 'object' && !Array.isArray(data.payload)
    ? data.payload as Record<string, unknown> : data;
  return {
    ...data,
    type,
    payload: type === 'content.delta' ? {
      ...payload, delta: payload.delta ?? data.content ?? '',
      block_id: payload.block_id ?? data.block_id ?? 'answer',
    } : payload,
  } as RuntimeEvent;
}

/** 重放幂等；新的epoch只通过权威快照接管，不接受迟到旧epoch。 */
export function applyResearchEvent(state: ResearchStreamState, event: RuntimeEvent): ResearchStreamState {
  if (state.runId && event.run_id && state.runId !== event.run_id) return state;
  const payload = event.payload;
  if (event.type === 'snapshot.reset') {
    const blocks = Array.isArray(payload.blocks) ? payload.blocks as ResearchBlock[] : [];
    return { runId: event.run_id ?? state.runId, epoch: event.stream_epoch,
      seq: Number(payload.committed_seq ?? event.seq ?? -1), blocks: publicResearchBlocks(blocks) };
  }
  if (state.epoch && event.stream_epoch && state.epoch !== event.stream_epoch) return state;
  if (typeof event.seq === 'number' && event.seq <= state.seq) return state;
  const next: ResearchStreamState = {
    ...state, runId: event.run_id ?? state.runId, epoch: event.stream_epoch ?? state.epoch,
    seq: typeof event.seq === 'number' ? event.seq : state.seq, blocks: state.blocks,
  };
  const blockId = (event.type.startsWith('review.') ? stringValue(payload.review_id) : stringValue(payload.block_id)) || (event.type.startsWith('reasoning.')
    ? payload.kind === 'provider_raw' ? 'provider-reasoning' : 'reasoning-summary' : 'answer');
  const previous = state.blocks.find((block) => block.id === blockId);
  let block: ResearchBlock | undefined;
  if (event.type === 'content.delta' || event.type === 'content.revised' || event.type === 'content.block_finished') {
    if (event.type === 'content.block_finished' && previous?.kind !== 'text') return next;
    const revision = Number(payload.revision ?? previous?.revision ?? 0);
    if (previous && revision < previous.revision) return next;
    const delta = stringValue(payload.delta ?? payload.content ?? payload.text);
    const phase = payload.content_phase ?? event.content_phase;
    const completion = payload.completion_status;
    block = { id: blockId, kind: 'text', revision,
      revision_of: Array.isArray(payload.revision_of) ? payload.revision_of.filter((id): id is string => typeof id === 'string')
        : previous?.kind === 'text' ? previous.revision_of : undefined,
      review_id: stringValue(payload.review_id) || (previous?.kind === 'text' ? previous.review_id : undefined),
      content_phase: phase === 'progress' || phase === 'answer' ? phase : previous?.kind === 'text' ? previous.content_phase : undefined,
      finish_reason: stringValue(payload.finish_reason) || (previous?.kind === 'text' ? previous.finish_reason : undefined),
      completion_status: completion === 'complete' || completion === 'tool_pending' || completion === 'incomplete'
        ? completion : previous?.kind === 'text' ? previous.completion_status : undefined,
      content: event.type === 'content.block_finished' ? previous?.kind === 'text' ? previous.content : ''
        : event.type === 'content.revised' ? delta : (previous?.kind === 'text' ? previous.content : '') + delta };
  } else if (event.type === 'review.started' || event.type === 'review.finished') {
    if (!isResearchReview(payload)) return next;
    if (previous?.kind === 'review' && previous.review.status !== 'running' && payload.status === 'running') return next;
    block = { id: payload.review_id, kind: 'review', review: payload, revision: payload.status === 'running' ? 0 : 1 };
  } else if (event.type.startsWith('reasoning.')) {
    const raw = payload.kind === 'provider_raw';
    const otherLength = state.blocks.reduce((count, item) => count + (item.id !== blockId && item.kind === 'reasoning'
      && item.reasoning_kind === 'provider_raw' ? item.content.length : 0), 0);
    const content = (previous?.kind === 'reasoning' ? previous.content : '') + stringValue(payload.delta ?? payload.content);
    const limit = Math.max(0, 20000 - otherLength);
    block = { id: blockId, kind: 'reasoning',
      content: raw ? content.slice(0, limit) : content, reasoning_kind: stringValue(payload.kind),
      truncated: raw && (content.length > limit || payload.truncated === true || (previous?.kind === 'reasoning' && previous.truncated)),
      duration_ms: typeof payload.duration_ms === 'number' ? payload.duration_ms : previous?.kind === 'reasoning' ? previous.duration_ms : undefined,
      provider: stringValue(payload.provider) || (previous?.kind === 'reasoning' ? previous.provider : undefined), revision: Number(payload.revision ?? 0) };
  } else if (event.type.startsWith('action.')) {
    const action = (payload.action ?? payload) as Record<string, unknown>;
    if (typeof action.action_id === 'string' && ['watchlist.add', 'watchlist.remove'].includes(String(action.action))) {
      block = { id: action.action_id, kind: 'action', action: action as unknown as Extract<ResearchBlock, { kind: 'action' }>['action'], revision: 0 };
    }
  } else if (event.type === 'artifact.ready') {
    const artifact = (payload.artifact ?? payload) as Record<string, unknown>;
    if (typeof artifact.artifact_id === 'string' && ['chart', 'table', 'image'].includes(String(artifact.kind))) {
      block = { id: artifact.artifact_id, kind: 'artifact', artifact: artifact as unknown as Extract<ResearchBlock, { kind: 'artifact' }>['artifact'],
        revision: Number(payload.revision ?? 0) };
    }
  }
  if (!block) return next;
  block = { ...block, seq: previous?.seq ?? event.seq,
    agent_id: stringValue(payload.agent_id ?? event.agent_id) || previous?.agent_id,
    agent_label: stringValue(payload.agent_label) || previous?.agent_label };
  const index = next.blocks.findIndex((candidate) => candidate.id === block!.id);
  next.blocks = index < 0 ? [...next.blocks, block] : next.blocks.map((candidate, i) => i === index ? block! : candidate);
  return next;
}

export function researchText(blocks: ResearchBlock[]): string {
  const superseded = new Set(blocks.flatMap((block) => block.kind === 'text' ? block.revision_of ?? [] : []));
  return blocks.filter((block): block is Extract<ResearchBlock, { kind: 'text' }> => block.kind === 'text'
      && block.content_phase !== 'progress' && !superseded.has(block.id))
    .map((block) => block.content).join('');
}

/** 修订块指向被核查的原版本；原文始终从已保存的正文块取得。 */
export function answerForReview(blocks: ResearchBlock[], reviewId: string, fallback: string): string {
  const originals = new Set(blocks.flatMap((block) => block.kind === 'text' && block.review_id === reviewId ? block.revision_of ?? [] : []));
  return originals.size ? blocks.filter((block): block is Extract<ResearchBlock, { kind: 'text' }> => block.kind === 'text' && originals.has(block.id))
    .map((block) => block.content).join('') : fallback;
}

/** 接收所属消息的对外内容；供应商思考按单run总量截断，未知块不进入视图。 */
export function publicResearchBlocks(blocks: ResearchBlock[]): ResearchBlock[] {
  if (!Array.isArray(blocks)) return [];
  let remaining = 20000;
  return blocks.filter((block) => block && typeof block.id === 'string'
    && ((block.kind === 'text' || block.kind === 'reasoning') ? typeof block.content === 'string'
      : block.kind === 'artifact' ? Boolean(block.artifact && typeof block.artifact.artifact_id === 'string')
        : block.kind === 'review' ? isResearchReview(block.review)
          : block.kind === 'action' && block.action && typeof block.action.action_id === 'string'))
    .map((block) => {
      if (block.kind !== 'reasoning' || block.reasoning_kind !== 'provider_raw') return block;
      const content = block.content.slice(0, remaining);
      remaining -= content.length;
      return { ...block, content, truncated: block.truncated || content.length < block.content.length };
    });
}

interface RuntimeMemory {
  owner: string | null;
  beginOwner(owner: string | null): void;
  clear(): void;
}

/** 身份切换由会话消息存储隔离；不再额外持有一份未保存的供应商思考。 */
export const useRuntimeMemory = create<RuntimeMemory>((set) => ({
  owner: null,
  beginOwner: (owner) => set({ owner }),
  clear: () => set({ owner: null }),
}));

