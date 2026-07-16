import { api } from '../http';
import { buildApiUrl } from '../../config/runtime';
import { buildAuthHeaders, ensureStreamResponseOk } from '../http';
import { parseSSEStream, withStreamGuards } from '../sse';
import type { StreamOpts } from '../sse';
import type * as Contracts from '../contracts';

export const chatApi = {
async createConversation(
    sessionId?: string,
    payload?: {
      title?: string;
      messages?: Array<Record<string, unknown>>;
      pinned?: boolean;
      archived?: boolean;
    },
  ): Promise<{
    success: boolean;
    session_id: string;
    conversation?: Record<string, unknown>;
  }> {
    const response = await api.post('/api/conversations', {
      ...(payload || {}),
      ...(sessionId ? { session_id: sessionId } : {}),
    });
    return response.data;
  },

/**
   * 读取后端会话快照 —— GET /api/conversations/{id}。
   * 用作 localStorage 为空时的回退真相源（换设备 / 清缓存后找回历史消息）。
   * conversation.messages 形如 [{ id, role, content, timestamp }]（后端已 sanitize）。
   */
  async getConversation(sessionId: string): Promise<{
    success: boolean;
    session_id: string;
    conversation?: Record<string, unknown>;
  }> {
    const response = await api.get(
      `/api/conversations/${encodeURIComponent(sessionId)}`,
    );
    return response.data;
  },

async patchConversation(
    sessionId: string,
    payload: {
      title?: string;
      messages?: Array<Record<string, unknown>>;
      pinned?: boolean;
      archived?: boolean;
    },
  ): Promise<{
    success: boolean;
    session_id: string;
    conversation?: Record<string, unknown>;
  }> {
    const response = await api.patch(`/api/conversations/${encodeURIComponent(sessionId)}`, payload);
    return response.data;
  },

async deleteConversation(sessionId: string): Promise<{
    success: boolean;
    session_id: string;
    cleared?: Record<string, unknown>;
  }> {
    const response = await api.delete(`/api/conversations/${encodeURIComponent(sessionId)}`);
    return response.data;
  },

// 流式发送消息 - SSE 逐字输出
  async sendMessageStream(
    body: Contracts.SendMessageBody,
    callbacks: Contracts.SSECallbacks,
    opts: StreamOpts = {},
  ): Promise<void> {
    let response = await fetch(buildApiUrl('/api/execute'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(await buildAuthHeaders()) },
      body: JSON.stringify(body),
      signal: opts.signal,
    });

    ensureStreamResponseOk(response);
    const guarded = withStreamGuards(callbacks, opts);
    const reconnectDelays = opts.reconnectDelaysMs ?? [1000, 4000];
    let runId = response.headers.get('X-Run-Id');
    let lastSeq = 0;
    let attempt = 0;

    opts.signal?.addEventListener('abort', () => {
      const activeRunId = runId;
      if (!activeRunId) return;
      void buildAuthHeaders().then((headers) => fetch(
        buildApiUrl(`/api/execute/runs/${encodeURIComponent(activeRunId)}/cancel`),
        { method: 'POST', headers },
      )).catch(() => undefined);
    }, { once: true });

    const waitForReconnect = async (delayMs: number): Promise<void> => {
      if (delayMs <= 0) return;
      await new Promise<void>((resolve, reject) => {
        const timer = setTimeout(resolve, delayMs);
        const abort = () => {
          clearTimeout(timer);
          reject(new DOMException('Aborted', 'AbortError'));
        };
        if (opts.signal?.aborted) abort();
        else opts.signal?.addEventListener('abort', abort, { once: true });
      });
    };

    while (!opts.signal?.aborted && !guarded.terminalState()) {
      try {
        await parseSSEStream(response, guarded, {
          ...opts,
          disconnectMode: 'throw',
          onEnvelope: (data) => {
            if (typeof data.run_id === 'string' && data.run_id) runId = data.run_id;
            if (typeof data.seq === 'number' && Number.isFinite(data.seq)) {
              lastSeq = Math.max(lastSeq, data.seq);
            }
          },
        });
        if (guarded.terminalState() || opts.signal?.aborted) break;
        throw new Error('stream ended before done');
      } catch {
        if (opts.signal?.aborted || guarded.terminalState()) break;
        if (!runId || attempt >= reconnectDelays.length) {
          opts.onConnectionState?.('lost', attempt);
          guarded.finish('连接中断，内容可能不完整，请重试');
          break;
        }

        attempt += 1;
        opts.onConnectionState?.('reconnecting', attempt);
        try {
          await waitForReconnect(reconnectDelays[attempt - 1]);
          response = await fetch(
            buildApiUrl(`/api/execute/runs/${encodeURIComponent(runId)}/events?after_seq=${lastSeq}`),
            {
              method: 'GET',
              headers: await buildAuthHeaders(),
              signal: opts.signal,
            },
          );
          ensureStreamResponseOk(response);
          opts.onConnectionState?.('connected', attempt);
        } catch (resumeError) {
          if (opts.signal?.aborted) break;
          if (attempt >= reconnectDelays.length) {
            opts.onConnectionState?.('lost', attempt);
            guarded.finish(
              response.status === 410
                ? '连接已过期，内容可能不完整，请重试'
                : `连接中断，内容可能不完整，请重试：${String(resumeError)}`,
            );
            break;
          }
        }
      }
    }
  },

/**
   * Trigger a non-chat agent execution via ``POST /api/execute``.
   *
   * Returns an SSE stream with the same event format as
   * ``sendMessageStream`` so any consumer can treat both identically.
   *
   * Supports an optional ``AbortSignal`` for cancellation.
   */
  async executeAgent(
    request: Contracts.ExecuteRequest & Record<string, unknown>,
    callbacks: Contracts.SSECallbacks,
    opts: Contracts.ExecuteAgentOptions = {},
  ): Promise<void> {
    const response = await fetch(buildApiUrl(opts.endpoint ?? '/api/execute'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(await buildAuthHeaders()) },
      body: JSON.stringify(request),
      signal: opts.signal,
    });

    ensureStreamResponseOk(response);
    const guarded = withStreamGuards(callbacks, opts);
    await parseSSEStream(response, guarded, opts);
    guarded.finish();
  }
};
