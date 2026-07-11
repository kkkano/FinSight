import { api } from '../http';
import { buildApiUrl } from '../../config/runtime';
import { buildAuthHeaders, emitRateLimitEvent, ensureStreamResponseOk, parseRetryAfter } from '../http';
import { parseSSEStream, withStreamGuards } from '../sse';
import type { StreamOpts } from '../sse';
import type * as Contracts from '../contracts';

export const chatApi = {
// 发送聊天消息（协调者主入口）
  async sendMessage(query: string, sessionId?: string, options?: Contracts.ChatOptions): Promise<Contracts.ChatResponse> {
    try {
      const response = await api.post<Contracts.ChatResponse>('/chat/supervisor', {
        query,
        session_id: sessionId,
        options,
      });

      // 兼容性处理：如果后端返回结构不一致，确保前端不白屏
      if (!response.data) {
        throw new Error("Empty response from server");
      }
      return response.data;
    } catch (error) {
      console.error("sendMessage failed:", error);
      throw error;
    }
  },

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
    const response = await fetch(buildApiUrl('/chat/supervisor/stream'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(await buildAuthHeaders()) },
      body: JSON.stringify(body),
      signal: opts.signal,
    });

    ensureStreamResponseOk(response);
    const guarded = withStreamGuards(callbacks, opts);
    await parseSSEStream(response, guarded, opts);
    guarded.finish();
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
  },

// --- Resume execution ---
  async resumeExecution(
    params: { thread_id: string; resume_value: unknown; session_id?: string; source?: string; run_id?: string },
    callbacks?: Contracts.SSECallbacks,
    opts?: { traceRawEnabled?: boolean; signal?: AbortSignal },
  ): Promise<Response> {
    const url = buildApiUrl('/api/execute/resume');
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(await buildAuthHeaders()) },
      body: JSON.stringify(params),
      signal: opts?.signal,
    });

    // P1-8: resume 流被限流时同样提示用户（不抛错，保持原有返回 Response 的契约）
    if (response.status === 429) {
      emitRateLimitEvent(parseRetryAfter(response.headers.get('retry-after')));
    }

    if (callbacks && response.ok) {
      const guarded = withStreamGuards(callbacks, opts);
      await parseSSEStream(response, guarded, opts);
      guarded.finish();
    }

    return response;
  }
};
