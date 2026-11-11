import { create } from 'zustand';
import type { ResearchBlock, ResearchStreamState, RuntimeEvent } from '../types/runtime';

export const emptyResearchStream = (runId?: string): ResearchStreamState => ({ runId, seq: -1, blocks: [] });

const stringValue = (value: unknown): string => typeof value === 'string' ? value : '';

const failureReasons: Record<string, string> = {
  model_timeout: '模型响应超时，研究已中断。',
  model_probe_timeout: '检查模型的工具调用能力时超时了。',
  TimeoutError: '处理超时，研究没有完成。',
  model_connection_error: '模型服务连接中断。',
  model_incomplete_stream: '模型响应提前结束，未返回完整研究结果。',
  model_empty_response: '模型未返回有效内容。',
  model_stream_error: '模型服务在生成过程中返回错误。',
  model_invalid_stream_json: '模型返回的数据格式无法读取。',
  model_tool_call_id_missing: '模型发出的工具请求缺少必要信息。',
  model_tool_calling_unsupported: '当前模型不支持研究所需的工具调用。',
  model_configuration_missing: '研究模型尚未配置。',
  agent_turn_budget_exhausted: '这次研究已达到步骤上限，还没完成。',
  provider_local_quota_exhausted: '模型调用额度已用尽。',
  CapacityExceeded: '研究服务正忙，请稍后重试。',
  tool_provider_error: '数据源没有返回可用结果。',
  tool_not_allowed: '当前助手没有使用这个工具的权限。',
  report_persistence_failed: '报告已生成，但未保存成功。',
};

/** SSE 与已保存终态使用同一展示规则，不把供应商堆栈当作用户说明。 */
export function researchFailureMessage(meta?: Record<string, unknown>, fallback = '研究没有完成，生成的内容已保留。'): string {
  const code = stringValue(meta?.error_code);
  const httpStatus = /^model_http_(\d{3})$/.exec(code)?.[1];
  const mapped = failureReasons[code] || (httpStatus ? `模型服务请求失败（HTTP ${httpStatus}）。` : '');
  const saved = meta?.assistant_message && typeof meta.assistant_message === 'object'
    ? meta.assistant_message as Record<string, unknown> : undefined;
  const messages = [meta?.message, saved?.error].map(stringValue);
  const specificMessage = messages.find((value) => value.trim()
    && !/^本轮研究未完成[，。]?\s*(已保留可用内容[。]?)?$/.test(value.trim()));
  const reason = [meta?.reason, meta?.failure_detail, meta?.error, specificMessage, mapped, ...messages]
    .map(stringValue).find((value) => value.trim()) || fallback;
  const displayReason = /^本轮研究未完成[，。]?\s*(已保留可用内容[。]?)?$/.test(reason.trim())
    ? '研究没有完成，生成的内容已保留。' : reason;
  const action = stringValue(meta?.recovery_action).trim();
  return action && !displayReason.includes(action) ? `${displayReason} ${action}` : displayReason;
}

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
  const blockId = stringValue(payload.block_id) || (event.type.startsWith('reasoning.')
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
      content_phase: phase === 'progress' || phase === 'answer' ? phase : previous?.kind === 'text' ? previous.content_phase : undefined,
      finish_reason: stringValue(payload.finish_reason) || (previous?.kind === 'text' ? previous.finish_reason : undefined),
      completion_status: completion === 'complete' || completion === 'tool_pending' || completion === 'incomplete'
        ? completion : previous?.kind === 'text' ? previous.completion_status : undefined,
      content: event.type === 'content.block_finished' ? previous?.kind === 'text' ? previous.content : ''
        : event.type === 'content.revised' ? delta : (previous?.kind === 'text' ? previous.content : '') + delta };
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
  return blocks.filter((block): block is Extract<ResearchBlock, { kind: 'text' }> => block.kind === 'text' && block.content_phase !== 'progress')
    .map((block) => block.content).join('');
}

/** 接收所属消息的对外内容；供应商思考按单run总量截断，未知块不进入视图。 */
export function publicResearchBlocks(blocks: ResearchBlock[]): ResearchBlock[] {
  if (!Array.isArray(blocks)) return [];
  let remaining = 20000;
  return blocks.filter((block) => block && typeof block.id === 'string'
    && ((block.kind === 'text' || block.kind === 'reasoning') ? typeof block.content === 'string'
      : block.kind === 'artifact' ? Boolean(block.artifact && typeof block.artifact.artifact_id === 'string')
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

