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

// === localStorage 键 ===
export const STORAGE_KEYS = {
  ACTIVE_ASSET: 'fs_dashboard_active_v1',
  WATCHLIST: 'fs_dashboard_watchlist_v1',
  LAYOUT: 'fs_dashboard_layout_v1',
  NEWS_MODE: 'fs_dashboard_news_mode_v1',
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
