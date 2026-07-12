// 确保 types/index.ts 文件定义了这些接口
// 如果没有，请将 type 导入行注释掉，使用 any 暂时代替
import type { RawSSEEvent, ReportIR, ThinkingStep } from '../types/index';
import type { SelectionItem } from '../types/dashboard';
import type { paths } from './schema';

/**
 * Chat Context - 临时上下文（不入库，仅本次请求生效）
 */
export interface ChatContext {
  active_symbol?: string;
  view?: string;
  selection?: SelectionItem;
  selections?: SelectionItem[];
  positions?: PortfolioSummaryPosition[];
  user_email?: string;
}

export interface ChatOptions {
  output_mode?: 'chat' | 'brief' | 'investment_report';
  strict_selection?: boolean;
  confirmation_mode?: 'auto' | 'required' | 'skip';
  locale?: string;
  trace_raw_override?: 'on' | 'off' | 'inherit';
  agent_preferences?: AgentPreferencesPayload;
  agents?: string[];
}

export interface SendMessageBody {
  query: string;
  history?: Array<{ role: string; content: string }>;
  context?: ChatContext;
  options?: ChatOptions;
  session_id?: string;
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

export interface AttributionPositionInput {
  ticker: string;
  weight: number;
}

export interface AttributionContribution {
  ticker: string;
  weight: number;
  return_pct: number | null;
  contribution_pct: number | null;
}

export interface PortfolioAttributionResponse {
  beta: number | null;
  factor_exposure: {
    factor_beta?: Record<string, number | null>;
    [key: string]: unknown;
  };
  contribution: AttributionContribution[];
  benchmark: {
    symbol: string;
    return_pct: number | null;
  };
  as_of: string;
  warnings: string[];
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
  timeoutSeconds?: number;
}

export interface ExecuteAgentOptions {
  traceRawEnabled?: boolean;
  signal?: AbortSignal;
  endpoint?: string;
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
  /** 仅当该要点确实来自 Agent 产出时由后端附带；确定性工具聚合保持缺省。 */
  analyst?: {
    name: string;
    display_name: string;
    short_zh: string;
    glyph: string;
    color_token: string;
  };
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
  strategy?: 'buy_and_hold' | 'ma_cross' | 'macd' | 'rsi_mean_reversion';
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

export interface BacktestPrefillConfig {
  tickers: string[];
  strategy: 'buy_and_hold' | 'ma_cross';
  start: string;
  end: string;
  rationale: string;
}

export interface BacktestPrefillResponse {
  config: BacktestPrefillConfig;
  warnings: string[];
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
  onDone?: (report?: ReportIR, thinking?: ThinkingStep[], meta?: any) => void;
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

/** 旧接口中尚未建模的松散 JSON 响应；公共字段显式化，扩展字段保持 unknown。 */
export interface ApiResponse {
  success?: boolean;
  detail?: string;
  error?: string;
  ticker_candidates?: string[];
  resolved_ticker?: string;
  should_generate?: boolean;
  chart_type?: string;
  data_kind?: string;
  title?: string;
  data?: Record<string, any>;
  profile?: Record<string, any>;
  subscriptions?: Array<{
    email: string;
    ticker: string;
    alert_types: string[];
    price_threshold: number | null;
    alert_mode?: 'price_change_pct' | 'price_target';
    price_target?: number | null;
    direction?: 'above' | 'below' | null;
    price_target_fired?: boolean;
    last_alert_at?: string;
    last_news_at?: string;
    disabled?: boolean;
    alert_failures?: number;
    last_alert_error?: string | null;
    last_alert_error_at?: string | null;
  }>;
  config?: Record<string, any>;
  [key: string]: unknown;
}

export type ConfigResponse = paths['/api/config']['get']['responses'][200]['content']['application/json'];
export type SaveConfigRequest = paths['/api/config']['post']['requestBody']['content']['application/json'];
export type SaveConfigResponse = ApiResponse;


export type { ChatResponse, KlineResponse, RawSSEEvent, RawEventType, ReportIR, ThinkingStep } from '../types/index';
export type { SelectionItem, DashboardInsightsResponse } from '../types/dashboard';
export type { FindingStatus, FindingsResponse, MonitorScanResponse, MonitorTargetsResponse, MonitorTargetResponse, CreateMonitorTargetParams, PatchMonitorTargetParams, MacroCalendarResponse, MonitorSettingsResponse, UpdateMonitorSettingsResponse } from '../types/monitor';
