export type Role = 'user' | 'assistant' | 'system';

export type Intent = 'chat' | 'report' | 'alert' | 'followup' | 'clarify' | 'unknown';

// 图表类型
export type ChartType = 'line' | 'candlestick' | 'pie' | 'bar' | 'tree' | 'area' | 'scatter' | 'heatmap';

export interface ThinkingStep {
  stage: string;
  message?: string;
  result?: any;
  timestamp: string;
}

export interface Message {
  id: string;
  role: Role;
  content: string;
  timestamp: number;
  intent?: Intent;
  relatedTicker?: string;
  isLoading?: boolean;
  thinking?: ThinkingStep[];  // 思考过程
  responseTime?: number;  // 响应时间（秒）
  error?: string;  // 错误信息
  canRetry?: boolean;  // 是否可以重试
  data_origin?: string;
  as_of?: string | null;
  fallback_used?: boolean;
  tried_sources?: string[];
  report?: ReportIR;  // Phase 2: 深度研报数据
}

export interface KlineData {
  time: string;
  open: number;
  close: number;
  high: number;
  low: number;
  volume?: number;
}

export interface ChatResponse {
  success: boolean;
  response: string;
  intent: Intent;
  current_focus?: string | null;
  response_time_ms: number;
  thinking_elapsed_seconds?: number;
  session_id: string;
  thinking?: ThinkingStep[];  // 思考过程
  data?: any;
  report?: ReportIR; // Phase 2: 深度研报数据
}

// Phase 2: Report IR Types - Updated
export type Sentiment = 'bullish' | 'bearish' | 'neutral';

export interface ReportContent {
  type: 'text' | 'chart' | 'table' | 'image';
  content: any; // string for text, object for chart/table
  metadata?: Record<string, any>;
}

export interface ReportSection {
  title: string;
  order: number;
  contents: ReportContent[];
}

export interface Citation {
  source_id: string;
  title: string;
  url: string;
  snippet: string;
  published_date?: string;
}

export interface ReportIR {
  report_id: string;
  ticker: string;
  company_name: string;
  title: string;
  summary: string;
  sentiment: Sentiment;
  confidence_score: number;
  generated_at: string;
  sections: ReportSection[];
  citations: Citation[];
  risks?: string[];
  recommendation?: string;
}

export interface KlineResponse {
  ticker: string;
  data: {
    kline_data?: KlineData[];
    error?: string;
    source?: string;
    period?: string;
    interval?: string;
  };
  cached?: boolean;
}
