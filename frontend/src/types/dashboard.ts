/**
 * Dashboard 类型定义 - 与后端 dashboard/schemas.py 一一对应
 */

// === 资产类型 ===
export type AssetType = 'equity' | 'index' | 'etf' | 'crypto' | 'portfolio';

export interface ActiveAsset {
  symbol: string;
  type: AssetType;
  display_name: string;
}

// === 能力集 ===
export interface Capabilities {
  revenue_trend: boolean;
  segment_mix: boolean;
  sector_weights: boolean;
  top_constituents: boolean;
  holdings: boolean;
  market_chart: boolean;
}

// === 自选列表 ===
export interface WatchItem {
  symbol: string;
  type: string;
  name: string;
}

// === 布局偏好 ===
export interface LayoutPrefs {
  hidden_widgets: string[];
  order: string[];
}

// === 新闻模式 ===
export type NewsModeType = 'market' | 'impact';

export interface NewsModeConfig {
  mode: NewsModeType;
}

// === 新闻子标签 / 标签分组 / 时间范围 (Phase H) ===
export type NewsSubTab = 'stock' | 'market' | 'breaking';
export type NewsTagGroup = '全部' | '财报' | '科技' | '宏观' | '并购' | '地缘' | '行业';
export type NewsTimeRange = '24h' | '7d' | '30d';

/** 用户友好标签分组 → 后端 NEWS_TAG_RULES 标签名映射 */
export const NEWS_TAG_GROUP_MAP: Record<NewsTagGroup, string[]> = {
  '全部': [],
  '财报': ['财报'],
  '科技': ['科技', 'AI', '半导体'],
  '宏观': ['宏观', '金融'],
  '并购': ['并购'],
  '地缘': ['地缘', '军事'],
  '行业': ['能源', '汽车', '消费', '医药', '地产', '加密', '中国', '美国', '监管'],
};

// === Dashboard 状态 ===
export interface DashboardState {
  active_asset: ActiveAsset;
  capabilities: Capabilities;
  watchlist: WatchItem[];
  layout_prefs: LayoutPrefs;
  news_mode: NewsModeConfig;
  debug: Record<string, unknown>;
}

// === 快照数据 ===
export interface SnapshotData {
  revenue?: number | null;
  eps?: number | null;
  gross_margin?: number | null;
  fcf?: number | null;
  index_level?: number | null;
  nav?: number | null;
}

// === 图表数据点 ===
export interface ChartPoint {
  time?: number;
  period?: string;
  name?: string;
  value?: number;
  open?: number;
  high?: number;
  low?: number;
  close?: number;
  volume?: number;
  weight?: number;
  symbol?: string;
}

// === 新闻条目 ===
export interface NewsItem {
  title: string;
  url: string;
  source?: string;
  ts: string;
  summary?: string;
  tags?: string[];                                  // 主题标签 (Phase H: 客户端计算或后端注入)
  impact_level?: 'high' | 'medium' | 'low';         // 影响级别 (Phase H: 客户端派生)
  time_decay?: number;
  source_reliability?: number;
  impact_score?: number;
  asset_relevance?: number;
  source_penalty?: number;
  ranking_score?: number;
  ranking_reason?: string;
  ranking_factors?: {
    mode?: string;
    half_life_hours?: number;
    weights?: Record<string, number>;
    weighted?: Record<string, number>;
  };
}

export interface NewsRankingWeights {
  time_decay: number;
  source_reliability: number;
  impact_score: number;
  asset_relevance: number;
}

export interface NewsRankingMeta {
  version: string;
  formula: string;
  weights?: Record<string, NewsRankingWeights>;
  half_life_hours?: Record<string, number>;
  notes?: string[];
}

export interface DataSourceMeta {
  provider: string;
  source_type: string;
  as_of: string;
  latency_ms: number;
  fallback_used: boolean;
  confidence: number;
  currency?: string;
  calc_window?: string;
  fallback_reason?: string | null;
}

// === 选中对象（用于 MiniChat 上下文引用） ===
export interface SelectionItem {
  type: 'news' | 'filing' | 'doc';
  id: string;           // hash(title + source + ts)
  title: string;
  url?: string;
  source?: string;
  ts?: string;
  snippet?: string;     // 摘要/前100字
}

// === Dashboard 数据 ===
export interface DashboardData {
  snapshot: SnapshotData;
  charts: Record<string, ChartPoint[]>;
  news: {
    market: NewsItem[];
    impact: NewsItem[];
    market_raw?: NewsItem[];
    impact_raw?: NewsItem[];
    ranking_meta?: NewsRankingMeta;
    [key: string]: NewsItem[] | NewsRankingMeta | undefined;
  };
  meta?: Record<string, DataSourceMeta>;
  // v2 fields
  valuation?: ValuationData | null;
  valuation_fallback_reason?: string | null;
  financials?: FinancialStatement | null;
  financials_fallback_reason?: string | null;
  technicals?: TechnicalData | null;
  technicals_fallback_reason?: string | null;
  peers?: PeerComparisonData | null;
  peers_fallback_reason?: string | null;
  // Phase G2 fields
  earnings_history?: EarningsHistoryEntry[] | null;
  analyst_targets?: AnalystTargets | null;
  recommendations?: RecommendationsSummary | null;
  indicator_series?: IndicatorSeries | null;
}

// === API 响应 ===
export interface DashboardResponse {
  success: boolean;
  state: DashboardState;
  data: DashboardData;
}

// === 错误响应 ===
export interface DashboardErrorDetail {
  code: number;
  message: string;
  details: Record<string, unknown>;
}

export interface DashboardErrorResponse {
  success: false;
  error: DashboardErrorDetail;
}

// === 持仓头寸（含成本） ===
export interface PortfolioPosition {
  /** 股票代码（大写） */
  symbol: string;
  /** 持有股数 */
  shares: number;
  /** 平均成本价（可选，用于 P&L 计算） */
  avgCost?: number;
}

// === 单个持仓 P&L 计算结果 ===
export interface PositionPnL {
  /** 股票代码 */
  symbol: string;
  /** 持有股数 */
  shares: number;
  /** 平均成本价 */
  avgCost: number;
  /** 当前价格（报价缺失时为 null） */
  currentPrice: number | null;
  /** 未实现盈亏金额（报价缺失时为 null） */
  unrealizedPnL: number | null;
  /** 未实现盈亏百分比（报价缺失时为 null） */
  pnlPercent: number | null;
  /** 持仓市值（报价缺失时为 null） */
  marketValue: number | null;
  /** 持仓成本 */
  costBasis: number;
}

// === 投资组合 P&L 汇总结果 ===
export interface PortfolioPnLResult {
  /** 各持仓明细 */
  positions: readonly PositionPnL[];
  /** 组合总市值（仅含有报价的持仓） */
  totalValue: number;
  /** 组合总成本（仅含有报价的持仓） */
  totalCost: number;
  /** 组合总盈亏金额 */
  totalPnL: number;
  /** 组合总盈亏百分比 */
  totalPnLPercent: number;
  /** 是否有部分持仓缺失报价 */
  hasPartialData: boolean;
}

// === v2 Valuation Data ===
export interface ValuationData {
  market_cap?: number | null;
  trailing_pe?: number | null;
  forward_pe?: number | null;
  price_to_book?: number | null;
  price_to_sales?: number | null;
  ev_to_ebitda?: number | null;
  dividend_yield?: number | null;
  beta?: number | null;
  week52_high?: number | null;
  week52_low?: number | null;
}

// === v2 Financial Statement ===
export interface FinancialStatement {
  periods: string[];
  revenue: (number | null)[];
  gross_profit: (number | null)[];
  operating_income: (number | null)[];
  net_income: (number | null)[];
  eps: (number | null)[];
  total_assets: (number | null)[];
  total_liabilities: (number | null)[];
  operating_cash_flow: (number | null)[];
  free_cash_flow: (number | null)[];
}

// === v2 Technical Data ===
export interface TechnicalData {
  close?: number | null;
  trend?: string | null;
  momentum?: string | null;
  ma5?: number | null;
  ma10?: number | null;
  ma20?: number | null;
  ma50?: number | null;
  ma100?: number | null;
  ma200?: number | null;
  ema12?: number | null;
  ema26?: number | null;
  rsi?: number | null;
  rsi_state?: string | null;
  macd?: number | null;
  macd_signal?: number | null;
  macd_hist?: number | null;
  stoch_k?: number | null;
  stoch_d?: number | null;
  adx?: number | null;
  cci?: number | null;
  williams_r?: number | null;
  bollinger_upper?: number | null;
  bollinger_middle?: number | null;
  bollinger_lower?: number | null;
  support_levels: number[];
  resistance_levels: number[];
  avg_volume?: number | null;
}

// === v2 Peer Comparison ===
export interface PeerMetrics {
  symbol: string;
  name: string;
  trailing_pe?: number | null;
  forward_pe?: number | null;
  price_to_book?: number | null;
  ev_to_ebitda?: number | null;
  net_margin?: number | null;
  roe?: number | null;
  revenue_growth?: number | null;
  dividend_yield?: number | null;
  market_cap?: number | null;
  score?: number | null;
}

export interface PeerComparisonData {
  subject_symbol: string;
  peers: PeerMetrics[];
}

// === Phase G2: New data types ===

export interface EarningsHistoryEntry {
  quarter: string;
  eps_estimate?: number | null;
  eps_actual?: number | null;
  surprise_pct?: number | null;
}

export interface AnalystTargets {
  low?: number | null;
  current?: number | null;
  mean?: number | null;
  median?: number | null;
  high?: number | null;
}

export interface RecommendationsSummary {
  buy: number;
  hold: number;
  sell: number;
  strong_buy: number;
  strong_sell: number;
}

export interface IndicatorSeries {
  dates: string[];
  rsi: (number | null)[];
  macd: (number | null)[];
  macd_signal: (number | null)[];
  macd_histogram: (number | null)[];
  bb_upper: (number | null)[];
  bb_middle: (number | null)[];
  bb_lower: (number | null)[];
}

// === Rebalance Types ===
export type ActionType = 'buy' | 'sell' | 'hold' | 'reduce' | 'increase';
export type RiskTier = 'conservative' | 'moderate' | 'aggressive';
export type SuggestionStatus = 'draft' | 'viewed' | 'dismissed' | 'sent_to_chat';

export interface RebalanceConstraints {
  max_single_position_pct: number;
  max_turnover_pct: number;
  sector_concentration_limit: number;
  min_action_delta_pct: number;
}

export interface EvidenceSnapshot {
  evidence_id: string;
  source: string;
  quote: string;
  report_id: string;
  captured_at: string;
}

export interface RebalanceAction {
  ticker: string;
  action: ActionType;
  current_weight: number;
  target_weight: number;
  delta_weight: number;
  reason: string;
  priority: number;
  evidence_ids: string[];
  evidence_snapshots: EvidenceSnapshot[];
}

export interface ExpectedImpact {
  diversification_delta: string;
  risk_delta: string;
  estimated_turnover_pct: number;
}

export interface RebalanceSuggestion {
  suggestion_id: string;
  mode: 'suggestion_only';
  executable: false;
  risk_tier: RiskTier;
  constraints: RebalanceConstraints;
  summary: string;
  actions: RebalanceAction[];
  expected_impact: ExpectedImpact;
  warnings: string[];
  disclaimer: string;
  status: SuggestionStatus;
  created_at: string;
  degraded_mode?: boolean;
  fallback_reason?: string | null;
}

export interface GenerateRebalanceParams {
  session_id: string;
  portfolio: { ticker: string; shares: number; avgCost?: number }[];
  risk_tier?: RiskTier;
  constraints?: Partial<RebalanceConstraints>;
  use_llm_enhancement?: boolean;
}

// === AI Insights (Phase F) ===
export interface InsightKeyMetric {
  label: string;
  value: string;
}

export interface InsightCard {
  agent_name: string;
  tab: string;
  score: number;             // 0-10
  score_label: string;       // 弱势 | 偏空 | 中性 | 偏多 | 强势
  summary: string;
  key_points: string[];
  risks: string[];
  key_metrics?: InsightKeyMetric[] | null;   // 结构化关键指标
  sub_scores?: Record<string, number>;
  confidence: number;
  as_of: string;
  model_generated: boolean;
}

export interface DashboardInsightsResponse {
  success: boolean;
  symbol: string;
  insights: Record<string, InsightCard>;
  generated_at: string;
  cached: boolean;
  cache_age_seconds: number;
}

// === localStorage 键 ===
export const STORAGE_KEYS = {
  ACTIVE_ASSET: 'fs_dashboard_active_v1',
  WATCHLIST: 'fs_dashboard_watchlist_v1',
  LAYOUT: 'fs_dashboard_layout_v1',
  NEWS_MODE: 'fs_dashboard_news_mode_v1',
  NEWS_SUB_TAB: 'fs_dashboard_news_sub_tab_v1',
  NEWS_TAG_FILTER: 'fs_dashboard_news_tag_filter_v1',
  NEWS_TIME_RANGE: 'fs_dashboard_news_time_range_v1',
  DEEP_ANALYSIS_INCLUDE_DEEPSEARCH: 'fs_dashboard_deep_analysis_include_deepsearch_v1',
} as const;

// === Widget ID 常量 ===
export const WIDGET_IDS = {
  SNAPSHOT: 'snapshot',
  REVENUE_TREND: 'revenue_trend',
  SEGMENT_MIX: 'segment_mix',
  SECTOR_WEIGHTS: 'sector_weights',
  TOP_CONSTITUENTS: 'top_constituents',
  HOLDINGS: 'holdings',
  MARKET_CHART: 'market_chart',
  NEWS_FEED: 'news_feed',
  MACRO: 'macro',
} as const;

// === 时间范围 ===
export type TimeRange = '1D' | '1W' | '1M' | '3M' | '6M' | '1Y' | '5Y';

export const TIME_RANGE_OPTIONS: { value: TimeRange; label: string }[] = [
  { value: '1D', label: '1天' },
  { value: '1W', label: '1周' },
  { value: '1M', label: '1月' },
  { value: '3M', label: '3月' },
  { value: '6M', label: '6月' },
  { value: '1Y', label: '1年' },
  { value: '5Y', label: '5年' },
];
