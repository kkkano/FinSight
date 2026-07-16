import type { RawEventType } from '../types/index';
import type { SSECallbacks } from './contracts';

/**
 * P1-2: SSE 读超时（毫秒）。超过该时长未收到任何数据帧（包括后端心跳）
 * 视为连接断开，向用户明确报错而不是让进度条永久卡住。设 0 禁用。
 */
const sseReadTimeoutMs = (): number => {
  const raw = Number(import.meta.env.VITE_SSE_READ_TIMEOUT_MS ?? 30000);
  if (!Number.isFinite(raw)) return 30000;
  return Math.max(0, raw);
};

/** 内部标记：SSE 读超时错误（与业务错误区分） */
const SSE_READ_TIMEOUT_ERROR = 'SSE_READ_TIMEOUT';

export interface StreamOpts {
  traceRawEnabled?: boolean;
  signal?: AbortSignal;
  readTimeoutMs?: number;
  reconnectDelaysMs?: number[];
  onConnectionState?: (state: 'reconnecting' | 'connected' | 'lost', attempt: number) => void;
}

export interface GuardedSSECallbacks extends SSECallbacks {
  clear(): void;
  finish(message?: string): void;
  terminalState(): 'done' | 'error' | null;
}

/** 统一聊天与 Agent SSE 的终态去重和异常结束处理。 */
export function withStreamGuards(
  callbacks: SSECallbacks,
  opts: Pick<StreamOpts, 'signal'> = {},
): GuardedSSECallbacks {
  let sawDone = false;
  let sawError = false;

  const clear = () => undefined;

  const guarded: GuardedSSECallbacks = {
    ...callbacks,
    onToken: (token) => {
      callbacks.onToken?.(token);
    },
    onThinking: (step) => {
      callbacks.onThinking?.(step);
    },
    onDone: (report, thinking, meta) => {
      if (sawDone || sawError) return;
      clear();
      sawDone = true;
      callbacks.onDone?.(report, thinking, meta);
    },
    onError: (error) => {
      if (sawDone || sawError) return;
      clear();
      sawError = true;
      callbacks.onError?.(error);
    },
    clear,
    finish: (message = '连接中断，内容可能不完整，请重试') => {
      clear();
      if (!opts.signal?.aborted && !sawDone && !sawError) {
        guarded.onError?.(message);
      }
    },
    terminalState: () => (sawDone ? 'done' : sawError ? 'error' : null),
  };
  return guarded;
}

/**
 * Parse an SSE response and dispatch callbacks.
 *
 * This function reads from a `fetch` Response body, splits SSE frames,
 * and dispatches typed callbacks. `/api/execute` is the single SSE
 * execution contract, so this parser is
 * fully reusable.
 */
export async function parseSSEStream(
  response: Response,
  callbacks: SSECallbacks,
  opts: {
    traceRawEnabled?: boolean;
    signal?: AbortSignal;
    readTimeoutMs?: number;
    disconnectMode?: 'callback' | 'throw';
    onEnvelope?: (data: Record<string, unknown>) => void;
  } = {},
): Promise<void> {
  const { onToken, onToolStart, onToolEnd, onDone, onError, onThinking, onRawEvent } = callbacks;
  const traceRawEnabled = opts.traceRawEnabled ?? true;
  const readTimeoutMs = opts.readTimeoutMs ?? sseReadTimeoutMs();

  const normalizeEventType = (payload: any): RawEventType => {
    const baseType = String(payload?.type || '').trim();
    if (!baseType) return 'any';
    if (baseType === 'thinking') {
      const stage = String(payload?.stage || '').toLowerCase();
      if (stage.includes('step_done')) return 'step_done';
    }
    return baseType as RawEventType;
  };

  const reader = response.body?.getReader();
  if (!reader) throw new Error('No reader available');

  const decoder = new TextDecoder('utf-8');
  let buffer = '';
  let eventCounter = 0;

  /**
   * P1-2: 带超时的 read。超过 readTimeoutMs 未收到任何数据（含心跳帧）
   * 视为连接断开（网络断/Tunnel 超时），避免 reader.read() 永久挂起。
   */
  const readWithTimeout = async (): Promise<ReadableStreamReadResult<Uint8Array>> => {
    if (readTimeoutMs <= 0) return reader.read();

    let timer: ReturnType<typeof setTimeout> | null = null;
    try {
      return await Promise.race([
        reader.read(),
        new Promise<never>((_, reject) => {
          timer = setTimeout(() => reject(new Error(SSE_READ_TIMEOUT_ERROR)), readTimeoutMs);
        }),
      ]);
    } finally {
      if (timer) clearTimeout(timer);
    }
  };

  try {
    while (true) {
      if (opts.signal?.aborted) break;

      let readResult: ReadableStreamReadResult<Uint8Array>;
      try {
        readResult = await readWithTimeout();
      } catch (e) {
        if (e instanceof Error && e.message === SSE_READ_TIMEOUT_ERROR) {
          // 中止前再确认一次没有被外部取消
          if (!opts.signal?.aborted) {
            const message = `连接中断：${Math.round(readTimeoutMs / 1000)} 秒未收到服务器数据`;
            if (opts.disconnectMode === 'throw') throw new Error(message);
            onError?.(message);
          }
          break;
        }
        throw e;
      }

      const { done, value } = readResult;
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;

        const rawJson = line.slice(6);
        try {
          const data = JSON.parse(rawJson);
          opts.onEnvelope?.(data);

          // 跳过后端 keep-alive / heartbeat 心跳帧（仅用于保持 Cloudflare Tunnel 连接）
          if (data.type === 'heartbeat' || data.type === 'keep-alive') continue;

          // Forward raw event to developer console
          if (onRawEvent && traceRawEnabled) {
            const eventType: RawEventType = normalizeEventType(data);
            onRawEvent({
              id: `sse-${Date.now()}-${eventCounter++}`,
              timestamp: new Date().toISOString(),
              eventType,
              rawData: rawJson,
              parsedData: data,
              size: new Blob([rawJson]).size,
              sessionId: typeof data.session_id === 'string' ? data.session_id : undefined,
              runId: typeof data.run_id === 'string' ? data.run_id : undefined,
            });
          }

          if (data.type === 'token' && data.content) {
            onToken?.(data.content);
          } else if (data.type === 'tool_start') {
            onToolStart?.(data.name);
            onThinking?.({
              stage: 'tool_start',
              message: data.message || `${data.name || 'tool'} start`,
              result: data,
              timestamp: data.timestamp || new Date().toISOString(),
              eventType: data.type,
              runId: typeof data.run_id === 'string' ? data.run_id : undefined,
              sessionId: typeof data.session_id === 'string' ? data.session_id : undefined,
            });
          } else if (data.type === 'tool_end') {
            onToolEnd?.();
            onThinking?.({
              stage: 'tool_end',
              message: data.message || `${data.name || data.tool || 'tool'} end`,
              result: data,
              timestamp: data.timestamp || new Date().toISOString(),
              eventType: data.type,
              runId: typeof data.run_id === 'string' ? data.run_id : undefined,
              sessionId: typeof data.session_id === 'string' ? data.session_id : undefined,
            });
          } else if (data.type === 'trace') {
            onThinking?.({
              stage: data.stage || 'trace',
              message: data.summary || data.title || data.userMessage || data.message || 'trace',
              result: data,
              timestamp: data.timestamp || new Date().toISOString(),
              eventType: 'trace',
              runId: typeof data.run_id === 'string' ? data.run_id : undefined,
              sessionId: typeof data.session_id === 'string' ? data.session_id : undefined,
            });
          } else if (data.type === 'thinking') {
            onThinking?.({
              stage: data.stage || 'any',
              message: data.userMessage || data.message,
              result: data.result,
              timestamp: data.timestamp || new Date().toISOString(),
              eventType: 'thinking',
              runId: typeof data.run_id === 'string' ? data.run_id : undefined,
              sessionId: typeof data.session_id === 'string' ? data.session_id : undefined,
            });
          } else if (
            ['llm_start', 'llm_end', 'llm_call', 'tool_call', 'tool_start', 'tool_end', 'cache_hit', 'cache_miss', 'cache_set', 'data_source', 'api_call', 'agent_step', 'step_start', 'step_done', 'step_error', 'plan_ready', 'pipeline_stage', 'decision_note', 'system', 'quality_blocked', 'degraded'].includes(data.type)
          ) {
            const stage = data.stage || data.type;
            const message =
              data.message ||
              (data.type === 'step_start' ? `${data.kind || 'step'} ${data.name || data.step_id || ''} started`.trim() : '') ||
              (data.type === 'step_done' ? `${data.kind || 'step'} ${data.name || data.step_id || ''} done`.trim() : '') ||
              (data.type === 'step_error' ? `${data.kind || 'step'} ${data.name || data.step_id || ''} error`.trim() : '') ||
              (data.type === 'tool_start' ? `${data.name || data.tool || 'tool'} start` : '') ||
              (data.type === 'tool_end' ? `${data.name || data.tool || 'tool'} end` : '') ||
              (data.type === 'cache_hit' ? `cache hit: ${data.key || ''}` : '') ||
              (data.type === 'cache_miss' ? `cache miss: ${data.key || ''}` : '') ||
              (data.type === 'cache_set' ? `cache set: ${data.key || ''}` : '') ||
              (data.type === 'api_call' ? `${data.method || 'GET'} ${data.endpoint || ''}` : '') ||
              (data.type === 'data_source' ? `${data.source || ''} ${data.query_type || ''}` : '') ||
              (data.type === 'agent_step' ? `${data.agent || ''} ${data.step || ''}` : '') ||
              data.type;

            onThinking?.({
              stage,
              message,
              result: data,
              timestamp: data.timestamp || new Date().toISOString(),
              eventType: data.type,
              runId: typeof data.run_id === 'string' ? data.run_id : undefined,
              sessionId: typeof data.session_id === 'string' ? data.session_id : undefined,
            });
          } else if (data.type === 'done') {
            onDone?.(data.report, data.thinking, data);
          } else if (data.type === 'error') {
            onError?.(data.message);
          } else if (
            ['supervisor_start', 'agent_start', 'agent_done', 'agent_error', 'forum_start', 'forum_done'].includes(data.type)
          ) {
            // Agent progress events — normalise into thinking format
            const agentName = data.agent || data.name;
            onThinking?.({
              stage: data.type,
              message: agentName ? `${agentName} Agent` : (data.message || ''),
              result: {
                ...data,
                agent: agentName,
              },
              timestamp: data.timestamp || new Date().toISOString(),
              eventType: data.type,
              runId: typeof data.run_id === 'string' ? data.run_id : undefined,
              sessionId: typeof data.session_id === 'string' ? data.session_id : undefined,
            });
          }
        } catch (e) {
          // Parse failure — still forward to console
          if (onRawEvent && traceRawEnabled) {
            onRawEvent({
              id: `sse-err-${Date.now()}-${eventCounter++}`,
              timestamp: new Date().toISOString(),
              eventType: 'any',
              rawData: rawJson,
              parsedData: { parseError: true, raw: rawJson, error: String(e) },
              size: new Blob([rawJson]).size,
              sessionId: undefined,
              runId: undefined,
            });
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
