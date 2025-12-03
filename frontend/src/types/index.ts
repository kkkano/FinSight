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
}

export interface KlineData {
  time: string;
  open: number;
  close: number;
  high: number;
  low: number;
  volume?: number;
}

export interface ThinkingStep {
  stage: string;
  message?: string;
  result?: any;
  timestamp: string;
}

export interface ChatResponse {
  success: boolean;
  response: string;
  intent: Intent;
  current_focus?: string | null;
  response_time_ms: number;
  session_id: string;
  thinking?: ThinkingStep[];  // 思考过程
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
