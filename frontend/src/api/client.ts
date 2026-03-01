import axios from 'axios';
// 确保 types/index.ts 文件定义了这些接口
// 如果没有，请将 type 导入行注释掉，使用 any 暂时代替
import type { ChatResponse, KlineResponse, RawSSEEvent, RawEventType } from '../types/index';
import type { SelectionItem, DashboardInsightsResponse } from '../types/dashboard';
import { API_BASE_URL, buildApiUrl } from '../config/runtime';

/**
 * Chat Context - 临时上下文（不入库，仅本次请求生效）
 */
export interface ChatContext {
  active_symbol?: string;
  view?: string;
  selection?: SelectionItem;
  selections?: SelectionItem[];
  user_email?: string;
}

export interface ChatOptions {
  output_mode?: 'chat' | 'brief' | 'investment_report';
  strict_selection?: boolean;
  confirmation_mode?: 'auto' | 'required' | 'skip';
  locale?: string;
  trace_raw_override?: 'on' | 'off' | 'inherit';
}

export interface ReportIndexItem {
  report_id: string;
  session_id: string;
  ticker?: string;
  analysis_depth?: 'quick' | 'report' | 'deep_research' | string;
  source_trigger?: string;
  title?: string;
  summary?: string;
  generated_at?: string;
  confidence_score?: number;
  is_favorite?: boolean;
  tags?: string[];
  source_type?: string;
  quality_state?: 'pass' | 'warn' | 'block';
  publishable?: boolean;
  quality_reasons?: Array<{
    code: string;
    severity: 'warn' | 'block';
    metric: string;
    actual?: unknown;
    threshold?: unknown;
    message: string;
  }>;
  created_at?: string;
  updated_at?: string;
}

export interface PortfolioSummaryPosition {
  ticker: string;
  shares: number;
  avg_cost?: number | null;
  updated_at?: string;
  live_price?: number | null;
  live_change?: number | null;
  live_change_percent?: number | null;
  price_source?: string;
  market_value: number;
  cost_basis: number;
  unrealized_pnl?: number | null;
  day_change?: number | null;
}

export interface PortfolioSummaryResponse {
  success: boolean;
  session_id: string;
  positions: PortfolioSummaryPosition[];
  count: number;
  priced_count?: number;
  total_value: number;
  total_cost: number;
  total_pnl: number;
  total_day_change?: number;
}

/**
 * Execute request — POST /api/execute
 */
export interface ExecuteRequest {
  query: string;
  tickers?: string[];
  output_mode?: string;
  confirmation_mode?: 'auto' | 'required' | 'skip';
  analysis_depth?: 'quick' | 'report' | 'deep_research';
  agents?: string[];
  budget?: number;
  source?: string;
  session_id?: string;
  run_id?: string;
  agent_preferences?: AgentPreferencesPayload;
}

export interface AgentPreferencesPayload {
  agents?: Record<string, string>;
  maxRounds?: number;
  concurrentMode?: boolean;
}

export interface AlertFeedEvent {
  id: string;
  email: string;
  ticker: string;
  event_type: string;
  severity: string;
  title: string;
  message: string;
  triggered_at: string;
  metadata?: Record<string, unknown>;
}

/** 晨报高亮条目 */
export interface MorningBriefHighlight {
  ticker: string;
  price: number | null;
  price_change: number | null;
  price_change_pct: number | null;
  trend: 'strong_up' | 'up' | 'neutral' | 'down' | 'strong_down';
  key_event: string;
}

/** 晨报数据 */
export interface MorningBriefData {
  date: string;
  summary: string;
  highlights: MorningBriefHighlight[];
  market_mood: string;
  market_mood_cn: string;
  action_items: string[];
  generated_at?: string;
  ticker_count?: number;
  priced_count?: number;
}

/** 晨报 API 响应 */
export interface MorningBriefResponse {
  success: boolean;
  brief: MorningBriefData;
}

export interface ScreenerRunRequest {
  market?: 'US' | 'CN' | 'HK';
  filters?: Record<string, unknown>;
  limit?: number;
  page?: number;
  sort_by?: string;
  sort_order?: 'asc' | 'desc';
}

export interface ScreenerRunResponse {
  success: boolean;
  market: string;
  items: Array<Record<string, unknown>>;
  count: number;
  source?: string;
  error?: string;
  warning?: string;
  capability_note?: string;
}

export interface CNMarketListResponse {
  success: boolean;
  items: Array<Record<string, unknown>>;
  count: number;
  source?: string;
  market?: string;
}

export interface BacktestRunRequest {
  ticker: string;
  strategy?: 'ma_cross' | 'macd' | 'rsi_mean_reversion';
  params?: Record<string, unknown>;
  start_date?: string;
  end_date?: string;
  initial_cash?: number;
  fee_bps?: number;
  slippage_bps?: number;
  t_plus_one?: boolean;
  market?: 'US' | 'CN' | 'HK';
}

export interface BacktestRunResponse {
  success: boolean;
  ticker?: string;
  strategy?: string;
  metrics?: Record<string, unknown>;
  trades?: Array<Record<string, unknown>>;
  equity_curve?: Array<Record<string, unknown>>;
  error?: string;
}

export interface ToolCapability {
  name: string;
  group: string;
  markets: string[];
  operations: string[];
  depths: string[];
  risk_level: string;
  timeout_ms: number;
  cache_ttl_s: number;
  requires_env: string[];
  default_enabled: boolean;
  env_ready: boolean;
  missing_env: string[];
  selected: boolean;
}

export interface ToolCapabilitiesResponse {
  success: boolean;
  market: string;
  operation: string;
  analysis_depth: 'quick' | 'report' | 'deep_research';
  output_mode: string;
  agents: string[];
  selected_tools: string[];
  tools: ToolCapability[];
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
  status?: 'pending' | 'done' | 'expired';
  expires_at?: string | null;
  report_id?: string | null;
  reason?: string;
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
  onInterrupt?: (data: {
    thread_id: string;
    prompt?: string;
    options?: string[];
    plan_summary?: string;
    required_agents?: string[];
    gate_reason_code?: string;
    gate_reason?: string;
    option_effects?: Record<string, string>;
    option_intents?: Record<string, string>;
    output_mode?: string;
    confirmation_mode?: string;
  }) => void;
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
          } else if (data.type === 'thinking') {
            onThinking?.({
              stage: data.stage || 'any',
              message: data.message,
              result: data.result,
              timestamp: data.timestamp || new Date().toISOString(),
              eventType: 'thinking',
              runId: typeof data.run_id === 'string' ? data.run_id : undefined,
              sessionId: typeof data.session_id === 'string' ? data.session_id : undefined,
            });
          } else if (
            ['llm_start', 'llm_end', 'llm_call', 'tool_call', 'tool_start', 'tool_end', 'cache_hit', 'cache_miss', 'cache_set', 'data_source', 'api_call', 'agent_step', 'step_start', 'step_done', 'step_error', 'plan_ready', 'pipeline_stage', 'decision_note', 'system', 'quality_blocked'].includes(data.type)
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
          } else if (data.type === 'interrupt') {
            onInterrupt?.({
              thread_id: data.thread_id || data.data?.thread_id || '',
              prompt: data.data?.prompt || data.prompt,
              options: data.data?.options || data.options,
              plan_summary: data.data?.plan_summary || data.plan_summary,
              required_agents: data.data?.required_agents || data.required_agents,
              gate_reason_code: data.data?.gate_reason_code || data.gate_reason_code,
              gate_reason: data.data?.gate_reason || data.gate_reason,
              option_effects: data.data?.option_effects || data.option_effects,
              option_intents: data.data?.option_intents || data.option_intents,
              output_mode: data.data?.output_mode || data.output_mode,
              confirmation_mode: data.data?.confirmation_mode || data.confirmation_mode,
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
    sourceType?: string;
    favoriteOnly?: boolean;
    includeBlocked?: boolean;
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
        source_type: params.sourceType,
        favorite_only: params.favoriteOnly,
        include_blocked: params.includeBlocked,
        limit: params.limit,
      },
    });
    return response.data;
  },

  async getReportReplay(params: {
    sessionId: string;
    reportId: string;
    includeBlocked?: boolean;
  }): Promise<{ success: boolean; session_id: string; report: any; citations: any[]; trace_digest: Record<string, any> }> {
    const response = await api.get(`/api/reports/replay/${encodeURIComponent(params.reportId)}`, {
      params: { session_id: params.sessionId, include_blocked: params.includeBlocked },
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
    includeBlocked?: boolean;
  }): Promise<{
    report_a: { report_id: string; title?: string | null; generated_at?: string | null };
    report_b: { report_id: string; title?: string | null; generated_at?: string | null };
    diff: {
      confidence_score: { a: number | null; b: number | null; delta: number | null };
      sentiment: { a: string | null; b: string | null; changed: boolean };
      risks: { added: string[]; removed: string[]; unchanged_count: number };
      summary: { a: string | null; b: string | null };
    };
  }> {
    const response = await api.get('/api/reports/compare', {
      params: {
        session_id: params.sessionId,
        id1: params.reportId1,
        id2: params.reportId2,
        include_blocked: params.includeBlocked,
      },
    });
    const raw = response.data;
    return {
      report_a: raw.report_a ?? { report_id: params.reportId1 },
      report_b: raw.report_b ?? { report_id: params.reportId2 },
      diff: raw.diff ?? {
        confidence_score: { a: null, b: null, delta: null },
        sentiment: { a: null, b: null, changed: false },
        risks: { added: [], removed: [], unchanged_count: 0 },
        summary: { a: null, b: null },
      },
    };
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

  async getAgentPreferences(user_id?: string): Promise<{
    success: boolean;
    user_id?: string;
    preferences?: AgentPreferencesPayload;
    error?: string;
  }> {
    const response = await api.get('/api/agents/preferences', {
      params: user_id ? { user_id } : {},
    });
    return response.data;
  },

  async updateAgentPreferences(payload: {
    user_id?: string;
    preferences: AgentPreferencesPayload;
  }): Promise<{
    success: boolean;
    user_id?: string;
    preferences?: AgentPreferencesPayload;
    error?: string;
  }> {
    const response = await api.put('/api/agents/preferences', payload);
    return response.data;
  },

  // 订阅管理
  async subscribe(payload: {
    email: string;
    ticker: string;
    alert_types?: string[];
    price_threshold?: number | null;
    alert_mode?: 'price_change_pct' | 'price_target';
    price_target?: number | null;
    direction?: 'above' | 'below';
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

  async listAlertFeed(params: {
    email: string;
    limit?: number;
    since?: string;
  }): Promise<{
    success: boolean;
    email: string;
    events: AlertFeedEvent[];
    count: number;
  }> {
    const response = await api.get('/api/alerts/feed', {
      params: {
        email: params.email,
        limit: params.limit,
        since: params.since,
      },
    });
    return response.data;
  },

  async getToolCapabilities(params?: {
    market?: string;
    operation?: string;
    analysis_depth?: 'quick' | 'report' | 'deep_research';
    output_mode?: string;
  }): Promise<ToolCapabilitiesResponse> {
    const response = await api.get<ToolCapabilitiesResponse>('/api/tools/capabilities', {
      params,
    });
    return response.data;
  },

  // --- Screener ---
  async runScreener(payload: ScreenerRunRequest): Promise<ScreenerRunResponse> {
    const response = await api.post<ScreenerRunResponse>('/api/screener/run', payload);
    return response.data;
  },

  async getScreenerFiltersMeta(): Promise<{
    success: boolean;
    markets: string[];
    sort_by: string[];
    sort_order: string[];
    filter_keys: string[];
    source?: string;
  }> {
    const response = await api.get('/api/screener/filters/meta');
    return response.data;
  },

  // --- CN Market ---
  async getCNFundFlow(limit: number = 20): Promise<CNMarketListResponse> {
    const response = await api.get<CNMarketListResponse>('/api/cn/market/fund-flow', { params: { limit } });
    return response.data;
  },

  async getCNNorthbound(limit: number = 20): Promise<CNMarketListResponse> {
    const response = await api.get<CNMarketListResponse>('/api/cn/market/northbound', { params: { limit } });
    return response.data;
  },

  async getCNLimitBoard(limit: number = 20): Promise<CNMarketListResponse> {
    const response = await api.get<CNMarketListResponse>('/api/cn/market/limit-board', { params: { limit } });
    return response.data;
  },

  async getCNLhb(limit: number = 20): Promise<CNMarketListResponse> {
    const response = await api.get<CNMarketListResponse>('/api/cn/market/lhb', { params: { limit } });
    return response.data;
  },

  async getCNConcept(params?: { keyword?: string; limit?: number }): Promise<CNMarketListResponse> {
    const response = await api.get<CNMarketListResponse>('/api/cn/market/concept', {
      params: { keyword: params?.keyword || '', limit: params?.limit || 20 },
    });
    return response.data;
  },

  // --- Backtest ---
  async runBacktest(payload: BacktestRunRequest): Promise<BacktestRunResponse> {
    const response = await api.post<BacktestRunResponse>('/api/backtest/run', payload);
    return response.data;
  },

  async listBacktestStrategies(): Promise<{
    success: boolean;
    strategies: Array<Record<string, unknown>>;
  }> {
    const response = await api.get('/api/backtest/strategies');
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
    params: { thread_id: string; resume_value: unknown; session_id?: string; source?: string; run_id?: string },
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

  // --- Morning Brief (一键晨报) ---
  async generateMorningBrief(params: {
    session_id: string;
    tickers: string[];
  }): Promise<MorningBriefResponse> {
    const response = await api.post<MorningBriefResponse>('/api/morning-brief/generate', params);
    return response.data;
  },

  // --- Dashboard Insights ---
  async getDashboardInsights(
    symbol: string,
    opts?: { force?: boolean; signal?: AbortSignal },
  ): Promise<DashboardInsightsResponse> {
    const params: Record<string, string | boolean> = { symbol };
    if (opts?.force) params.force = true;
    const response = await api.get<DashboardInsightsResponse>('/api/dashboard/insights', {
      params,
      signal: opts?.signal,
    });
    return response.data;
  },

  // --- Portfolio ---
  async getPortfolioSummary(sessionId: string): Promise<PortfolioSummaryResponse> {
    const response = await api.get<PortfolioSummaryResponse>('/api/portfolio/summary', { params: { session_id: sessionId } });
    return response.data;
  },

  async syncPortfolioPositions(
    sessionId: string,
    positions: Array<{ ticker: string; shares: number; avg_cost?: number | null }>,
  ): Promise<{ success: boolean; session_id: string; synced_count: number }> {
    const response = await api.post('/api/portfolio/positions', { session_id: sessionId, positions });
    return response.data;
  },
};
