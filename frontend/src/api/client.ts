import axios from 'axios';
// 确保 types/index.ts 文件定义了这些接口
// 如果没有，请将 type 导入行注释掉，使用 any 暂时代替
import type { ChatResponse, KlineResponse, RawSSEEvent, RawEventType } from '../types/index';
import type { SelectionItem } from '../types/dashboard';
import { API_BASE_URL, buildApiUrl } from '../config/runtime';

/**
 * Chat Context - 临时上下文（不入库，仅本次请求生效）
 */
export interface ChatContext {
  active_symbol?: string;
  view?: string;
  selection?: SelectionItem;
  selections?: SelectionItem[];
}

export interface ChatOptions {
  output_mode?: 'chat' | 'brief' | 'investment_report';
  strict_selection?: boolean;
  locale?: string;
  trace_raw_override?: 'on' | 'off' | 'inherit';
}

export interface ReportIndexItem {
  report_id: string;
  session_id: string;
  ticker?: string;
  title?: string;
  summary?: string;
  generated_at?: string;
  confidence_score?: number;
  is_favorite?: boolean;
  tags?: string[];
  created_at?: string;
  updated_at?: string;
}

/**
 * Execute request — POST /api/execute
 */
export interface ExecuteRequest {
  query: string;
  tickers?: string[];
  output_mode?: string;
  agents?: string[];
  budget?: number;
  source?: string;
  session_id?: string;
  agent_preferences?: {
    agents?: Record<string, string>;
    maxRounds?: number;
    concurrentMode?: boolean;
  };
}

/**
 * Daily task item — GET /api/tasks/daily
 */
export interface DailyTask {
  id: string;
  title: string;
  category: string;
  priority: number;
  action_url: string;
  icon: string;
  /** 可执行任务的参数 — 直接传给 executeAgent()。导航型任务为 null。 */
  execution_params: ExecuteRequest | null;
}

/**
 * SSE event callbacks shared between sendMessageStream & executeAgent.
 */
export interface SSECallbacks {
  onToken?: (token: string) => void;
  onToolStart?: (name: string) => void;
  onToolEnd?: () => void;
  onDone?: (report?: any, thinking?: any[], meta?: any) => void;
  onError?: (error: string) => void;
  onThinking?: (step: any) => void;
  onRawEvent?: (event: RawSSEEvent) => void;
  onInterrupt?: (data: { thread_id: string; prompt?: string; options?: string[]; plan_summary?: string; required_agents?: string[] }) => void;
}

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json; charset=utf-8',
  },
  timeout: 120000, // 120秒超时，防止 LLM 生成长文时前端断开
});

// 响应拦截器：处理后端返回的非 200 错误
api.interceptors.response.use(
  (response) => response,
  (error) => {
    console.error('API Error:', error.response || error.message);
    return Promise.reject(error);
  }
);

export const createCancelToken = () => {
  return axios.CancelToken.source();
};

// ---------------------------------------------------------------------------
// Shared SSE parser — used by sendMessageStream() and executeAgent()
// ---------------------------------------------------------------------------

/**
 * Parse an SSE response and dispatch callbacks.
 *
 * This function reads from a `fetch` Response body, splits SSE frames,
 * and dispatches typed callbacks.  Both `/chat/supervisor/stream` and
 * `/api/execute` return identical SSE wire format so this parser is
 * fully reusable.
 */
export async function parseSSEStream(
  response: Response,
  callbacks: SSECallbacks,
  opts: { traceRawEnabled?: boolean; signal?: AbortSignal } = {},
): Promise<void> {
  const { onToken, onToolStart, onToolEnd, onDone, onError, onThinking, onRawEvent, onInterrupt } = callbacks;
  const traceRawEnabled = opts.traceRawEnabled ?? true;

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

  try {
    while (true) {
      if (opts.signal?.aborted) break;

      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;

        const rawJson = line.slice(6);
        try {
          const data = JSON.parse(rawJson);

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
            });
          }

          if (data.type === 'token' && data.content) {
            onToken?.(data.content);
          } else if (data.type === 'tool_start') {
            onToolStart?.(data.name);
          } else if (data.type === 'tool_end') {
            onToolEnd?.();
          } else if (data.type === 'thinking') {
            onThinking?.({
              stage: data.stage || 'any',
              message: data.message,
              result: data.result,
              timestamp: data.timestamp || new Date().toISOString(),
            });
          } else if (
            ['llm_start', 'llm_end', 'llm_call', 'tool_call', 'cache_hit', 'cache_miss', 'cache_set', 'data_source', 'api_call', 'agent_step', 'system'].includes(data.type)
          ) {
            const stage = data.stage || data.type;
            const message =
              data.message ||
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
            });
          } else if (data.type === 'done') {
            onDone?.(data.report, data.thinking, data);
          } else if (data.type === 'error') {
            onError?.(data.message);
          } else if (data.type === 'interrupt') {
            onInterrupt?.({
              thread_id: data.thread_id || data.data?.thread_id || '',
              prompt: data.data?.prompt || data.prompt,
              options: data.data?.options || data.options,
              plan_summary: data.data?.plan_summary || data.plan_summary,
              required_agents: data.data?.required_agents || data.required_agents,
            });
          } else if (
            ['supervisor_start', 'agent_start', 'agent_done', 'agent_error', 'forum_start', 'forum_done'].includes(data.type)
          ) {
            // Agent progress events — normalise into thinking format
            const agentName = data.agent || data.name;
            onThinking?.({
              stage: data.type,
              message: agentName ? `${agentName} Agent` : (data.message || ''),
              result: {
                agent: agentName,
                status: data.status,
                step_id: data.step_id,
                inputs: data.inputs,
                error: data.error,
                agents: data.agents,
              },
              timestamp: new Date().toISOString(),
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
            });
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

export const apiClient = {
  // 发送聊天消息（协调者主入口）
  async sendMessage(query: string, sessionId?: string, options?: ChatOptions): Promise<ChatResponse> {
    try {
      const response = await api.post<ChatResponse>('/chat/supervisor', {
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

  // 获取 K 线数据
  async fetchKline(ticker: string, period: string = "1y", interval: string = "1d"): Promise<KlineResponse> {
    const response = await api.get<KlineResponse>(`/api/stock/kline/${ticker}`, {
      params: { period, interval }
    });
    return response.data;
  },

  async fetchStockPrice(ticker: string): Promise<any> {
    const response = await api.get(`/api/stock/price/${encodeURIComponent(ticker)}`);
    return response.data;
  },

  // 将图表数据加入聊天上下文
  async addChartData(ticker: string, summary: string): Promise<any> {
    const response = await api.post('/api/chat/add-chart-data', {
      ticker,
      summary
    });
    return response.data;
  },

  // 智能检测图表类型
  async detectChartType(query: string, ticker?: string): Promise<any> {
    try {
      const response = await api.post('/api/chart/detect', {
        query,
        ticker
      });
      return response.data;
    } catch {
      // 即使检测失败也不要阻断流程，返回默认值
      return { success: false, should_generate: false };
    }
  },

  // 获取用户配置
  async getConfig(): Promise<any> {
    const response = await api.get('/api/config');
    return response.data;
  },

  // 保存用户配置
  async saveConfig(config: any): Promise<any> {
    const response = await api.post('/api/config', config);
    return response.data;
  },

  async listReportIndex(params: {
    sessionId: string;
    ticker?: string;
    query?: string;
    dateFrom?: string;
    dateTo?: string;
    tag?: string;
    favoriteOnly?: boolean;
    limit?: number;
  }): Promise<{ success: boolean; session_id: string; items: ReportIndexItem[]; count: number }> {
    const response = await api.get('/api/reports/index', {
      params: {
        session_id: params.sessionId,
        ticker: params.ticker,
        query: params.query,
        date_from: params.dateFrom,
        date_to: params.dateTo,
        tag: params.tag,
        favorite_only: params.favoriteOnly,
        limit: params.limit,
      },
    });
    return response.data;
  },

  async getReportReplay(params: {
    sessionId: string;
    reportId: string;
  }): Promise<{ success: boolean; session_id: string; report: any; citations: any[]; trace_digest: Record<string, any> }> {
    const response = await api.get(`/api/reports/replay/${encodeURIComponent(params.reportId)}`, {
      params: { session_id: params.sessionId },
    });
    return response.data;
  },

  async setReportFavorite(params: {
    sessionId: string;
    reportId: string;
    isFavorite: boolean;
  }): Promise<{ success: boolean; session_id: string; report_id: string; is_favorite: boolean }> {
    const response = await api.post(`/api/reports/${encodeURIComponent(params.reportId)}/favorite`, {
      session_id: params.sessionId,
      is_favorite: params.isFavorite,
    });
    return response.data;
  },

  /** Compare two reports — GET /api/reports/compare */
  async compareReports(params: {
    sessionId: string;
    reportId1: string;
    reportId2: string;
  }): Promise<{
    confidence_score: { a: number | null; b: number | null; delta: number | null };
    sentiment: { a: string | null; b: string | null; changed: boolean };
    risks: { added: string[]; removed: string[]; unchanged_count: number };
    summary: { a: string | null; b: string | null };
  }> {
    const response = await api.get('/api/reports/compare', {
      params: {
        session_id: params.sessionId,
        id1: params.reportId1,
        id2: params.reportId2,
      },
    });
    // Backend wraps diff data in { success, report_a, report_b, diff: {...} }
    const raw = response.data;
    return raw.diff ?? raw;
  },

  // User profile / watchlist
  async getUserProfile(user_id?: string): Promise<any> {
    const response = await api.get('/api/user/profile', {
      params: user_id ? { user_id } : {},
    });
    return response.data;
  },

  async addWatchlist(payload: { user_id?: string; ticker: string }): Promise<any> {
    const response = await api.post('/api/user/watchlist/add', payload);
    return response.data;
  },

  async removeWatchlist(payload: { user_id?: string; ticker: string }): Promise<any> {
    const response = await api.post('/api/user/watchlist/remove', payload);
    return response.data;
  },

  // 订阅管理
  async subscribe(payload: {
    email: string;
    ticker: string;
    alert_types?: string[];
    price_threshold?: number | null;
  }): Promise<any> {
    const response = await api.post('/api/subscribe', payload);
    return response.data;
  },

  async unsubscribe(payload: { email: string; ticker?: string | null }): Promise<any> {
    const response = await api.post('/api/unsubscribe', payload);
    return response.data;
  },

  async listSubscriptions(email?: string): Promise<any> {
    const response = await api.get('/api/subscriptions', {
      params: email ? { email } : {},
    });
    return response.data;
  },

  async toggleSubscription(payload: { email: string; ticker: string; enabled: boolean }): Promise<any> {
    const response = await api.post('/api/subscription/toggle', payload);
    return response.data;
  },

  // 导出 PDF
  async exportPDF(messages: any[], charts?: any[], title?: string): Promise<Blob> {
    const response = await api.post('/api/export/pdf', {
      messages,
      charts: charts || [],
      title: title || 'FinSight 对话记录'
    }, {
      responseType: 'blob' // 关键：声明返回二进制流
    });
    return response.data;
  },

  async diagnosticsOrchestrator(): Promise<any> {
    const response = await api.get('/diagnostics/orchestrator');
    return response.data;
  },

  // 健康检查（含子Agent状态）
  async healthCheck(): Promise<any> {
    const response = await api.get('/health');
    return response.data;
  },

  // 流式发送消息 - SSE 逐字输出（委托给共享 parseSSEStream）
  async sendMessageStream(
    query: string,
    onToken: (token: string) => void,
    onToolStart?: (name: string) => void,
    onToolEnd?: () => void,
    onDone?: (report?: any, thinking?: any[], meta?: any) => void,
    onError?: (error: string) => void,
    onThinking?: (step: any) => void,
    history?: Array<{role: string, content: string}>,
    onRawEvent?: (event: RawSSEEvent) => void,
    context?: ChatContext,
    options?: ChatOptions,
    sessionId?: string,
    traceRawEnabled: boolean = true,
  ): Promise<void> {
    const body: Record<string, any> = { query, history };
    if (sessionId) body.session_id = sessionId;
    if (context) body.context = context;
    if (options) body.options = options;

    const response = await fetch(buildApiUrl('/chat/supervisor/stream'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    await parseSSEStream(
      response,
      { onToken, onToolStart, onToolEnd, onDone, onError, onThinking, onRawEvent },
      { traceRawEnabled },
    );
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
    request: ExecuteRequest,
    callbacks: SSECallbacks,
    opts: { traceRawEnabled?: boolean; signal?: AbortSignal } = {},
  ): Promise<void> {
    const response = await fetch(buildApiUrl('/api/execute'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
      signal: opts.signal,
    });

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    await parseSSEStream(response, callbacks, opts);
  },

  /**
   * Fetch personalized daily tasks from ``GET /api/tasks/daily``.
   *
   * Tasks with ``execution_params`` can be directly passed to
   * ``executeAgent()`` for in-place execution.
   */
  async getDailyTasks(params: {
    session_id: string;
    news_count?: number;
    risk_preference?: string;
    watchlist?: string[];
  }): Promise<{
    success: boolean;
    session_id: string;
    risk_preference: string;
    watchlist: string[];
    tasks: DailyTask[];
    count: number;
  }> {
    const searchParams = new URLSearchParams();
    searchParams.set('session_id', params.session_id);
    if (params.news_count !== undefined) {
      searchParams.set('news_count', String(params.news_count));
    }
    if (params.risk_preference) {
      searchParams.set('risk_preference', params.risk_preference);
    }
    if (params.watchlist && params.watchlist.length > 0) {
      searchParams.set('watchlist', params.watchlist.join(','));
    }
    const { data } = await api.get(`/api/tasks/daily?${searchParams.toString()}`);
    return data;
  },

  // --- Rebalance ---
  async generateRebalanceSuggestion(params: Record<string, unknown>): Promise<unknown> {
    const response = await api.post('/api/rebalance/suggestions/generate', params);
    return response.data;
  },

  async listRebalanceSuggestions(sessionId: string, limit = 10): Promise<unknown> {
    const response = await api.get('/api/rebalance/suggestions', { params: { session_id: sessionId, limit } });
    return response.data;
  },

  async patchRebalanceSuggestion(suggestionId: string, body: { status: string }): Promise<unknown> {
    const response = await api.patch(`/api/rebalance/suggestions/${encodeURIComponent(suggestionId)}`, body);
    return response.data;
  },

  // --- Resume execution ---
  async resumeExecution(
    params: { thread_id: string; resume_value: unknown; session_id?: string; source?: string },
    callbacks?: SSECallbacks,
    opts?: { traceRawEnabled?: boolean; signal?: AbortSignal },
  ): Promise<Response> {
    const url = buildApiUrl('/api/execute/resume');
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
      signal: opts?.signal,
    });

    if (callbacks && response.ok) {
      await parseSSEStream(response.clone(), callbacks, opts);
    }

    return response;
  },

  // --- Portfolio ---
  async getPortfolioSummary(sessionId: string): Promise<unknown> {
    const response = await api.get('/api/portfolio/summary', { params: { session_id: sessionId } });
    return response.data;
  },

  async syncPortfolioPositions(sessionId: string, positions: unknown[]): Promise<unknown> {
    const response = await api.post('/api/portfolio/positions', { session_id: sessionId, positions });
    return response.data;
  },
};
