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

// Evidence item for citations/sources
export interface EvidenceItem {
  title?: string;
  source?: string;
  url?: string;
  snippet?: string;
  confidence?: number;
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
  evidence_pool?: EvidenceItem[];  // Evidence/citations pool
  via?: 'main' | 'mini';  // 消息来源入口：主聊天区 or 右侧面板 MiniChat
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
  citation_refs?: string[];
  metadata?: Record<string, any>;
}

export interface ReportSection {
  title: string;
  order: number;
  contents: ReportContent[];
  confidence?: number;
  agent_name?: string;
  data_sources?: string[];
  subsections?: ReportSection[];
  is_collapsible?: boolean;
  default_collapsed?: boolean;
}

export interface Citation {
  source_id: string;
  title: string;
  url: string;
  snippet: string;
  published_date?: string;
  confidence?: number;        // 来源可信度 (0.0 - 1.0)
  freshness_hours?: number;   // 新鲜度（小时）
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
  // Forum 整合的完整报告文本（≥2000字）
  synthesis_report?: string;
  sections: ReportSection[];
  citations: Citation[];
  risks?: string[];
  recommendation?: string;
  // Phase 2 扩展字段
  meta?: {
    agent_traces?: Record<string, any>;
    data_context?: Record<string, any>;
    [key: string]: any;
  };
  agent_status?: Record<string, {
    status: string;
    confidence?: number;
    error?: string;
    skipped_reason?: string;
    escalation_not_needed?: boolean;
    evidence_quality?: {
      overall_score?: number;
      source_diversity?: number;
      has_conflicts?: boolean;
      [key: string]: any;
    };
    data_sources?: string[];
  }>;
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

// Agent Log Types - 用于实时日志面板
export type AgentLogLevel = 'info' | 'debug' | 'warn' | 'error' | 'success';

export type AgentLogSource =
  | 'supervisor'
  | 'router'
  | 'gate'
  | 'planner'
  | 'news_agent'
  | 'price_agent'
  | 'fundamental_agent'
  | 'technical_agent'
  | 'macro_agent'
  | 'deep_search_agent'
  | 'forum'
  | 'system';

export interface AgentLogEntry {
  id: string;
  timestamp: string;
  source: AgentLogSource;
  level: AgentLogLevel;
  message: string;
  details?: Record<string, any>;  // JSON 格式的详细数据
  duration_ms?: number;           // 执行耗时
  tool_name?: string;             // 使用的工具名称
  tool_input?: any;               // 工具输入
  tool_output?: any;              // 工具输出
}

export interface AgentStatus {
  source: AgentLogSource;
  status: 'idle' | 'running' | 'success' | 'error' | 'waiting';
  startTime?: string;
  endTime?: string;
  lastMessage?: string;
  progress?: number;  // 0-100
}

// Raw SSE Event - 开发者控制台原始事件
// 包含所有 TraceEmitter 发射的事件类型
export type RawEventType =
  // Token 流式输出
  | 'token'
  // 思考步骤
  | 'thinking'
  // 工具调用
  | 'tool_start'
  | 'tool_end'
  | 'tool_call'
  // LLM 调用
  | 'llm_call'
  | 'llm_start'
  | 'llm_end'
  // 缓存操作
  | 'cache_hit'
  | 'cache_miss'
  | 'cache_set'
  // 数据源和 API
  | 'data_source'
  | 'api_call'
  // Agent 执行
  | 'agent_start'
  | 'agent_done'
  | 'agent_step'
  | 'agent_error'
  // Supervisor 执行
  | 'supervisor_start'
  | 'supervisor_done'
  // Forum 综合
  | 'forum_start'
  | 'forum_done'
  // 系统事件
  | 'system'
  // 完成和错误
  | 'done'
  | 'error'
  // 未知类型兜底
  | 'unknown';

export interface RawSSEEvent {
  id: string;                    // 唯一标识
  timestamp: string;             // ISO 时间戳
  eventType: RawEventType;       // 事件类型
  rawData: string;               // 原始 JSON 字符串
  parsedData: any;               // 解析后的数据对象
  size: number;                  // 数据大小（字节）
  sessionId?: string;            // 会话 ID
}

// Console Filter Options
export interface ConsoleFilterOptions {
  eventTypes: RawEventType[];    // 要显示的事件类型
  searchText: string;            // 搜索文本
  showRawJson: boolean;          // 是否显示原始 JSON
  autoScroll: boolean;           // 自动滚动
  maxEvents: number;             // 最大事件数
}
