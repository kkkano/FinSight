// 确保 types/index.ts 文件定义了这些接口
// 如果没有，请将 type 导入行注释掉，使用 any 暂时代替
import type { RawSSEEvent, ReportIR, ThinkingStep } from '../types/index';
import type { SelectionItem } from '../types/dashboard';

/**
 * Chat Context - 临时上下文（不入库，仅本次请求生效）
 */
export interface ChatContext {
  active_symbol?: string;
  view?: string;
  source_view?: 'dashboard' | 'command_palette';
  source_tab?: string;
  selection?: SelectionItem;
  selections?: SelectionItem[];
}

export interface ChatOptions {
  output_mode?: 'chat' | 'brief' | 'investment_report';
  strict_selection?: boolean;
  locale?: string;
  trace_raw_override?: 'on' | 'off' | 'inherit';
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

/**
 * Execute request — POST /api/execute
 */
export interface ExecuteRequest {
  query: string;
  tickers?: string[];
  output_mode?: string;
  analysis_depth?: 'quick' | 'report' | 'deep_research';
  budget?: number;
  source?: string;
  session_id?: string;
  run_id?: string;
}

export interface ExecuteAgentOptions {
  traceRawEnabled?: boolean;
  signal?: AbortSignal;
  endpoint?: string;
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
}

export type {
  ChatResponse,
  KlineResponse,
  MarketDataResponse,
  QuoteData,
  RawSSEEvent,
  RawEventType,
  ReportIR,
  ThinkingStep,
} from '../types/index';
export type { SelectionItem } from '../types/dashboard';
