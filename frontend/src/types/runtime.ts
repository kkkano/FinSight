/** 当前轮图片输入，禁止写入普通Message或requestSnapshot。 */
export interface ChatImageInput {
  data_url: string;
  name?: string;
}

export interface ResearchSkill {
  id: string;
  name: string;
  description: string;
  category: string;
}

/** 服务端研究运行事件；身份必须来自当前请求。 */
export interface RuntimeEvent {
  schema_version?: string | number;
  type: string;
  run_id?: string;
  session_id?: string;
  message_id?: string;
  agent_id?: string;
  attempt_id?: string;
  stream_epoch?: string;
  event_id?: string;
  seq?: number;
  timestamp?: string;
  content_phase?: 'progress' | 'answer';
  payload: Record<string, unknown>;
}

/** 面向用户的有界活动详情；输入与结果在服务端脱敏后发送。 */
export interface RuntimeActivityDetails {
  display?: { target: string; result: string };
  inputs?: unknown;
  output_preview?: unknown;
  sources?: unknown;
  source_refs?: unknown;
  data_refs?: unknown;
  evidence_refs?: unknown;
  reason?: string;
  error_code?: string;
  recovery_action?: string;
  limitations?: unknown;
  role?: string;
  task?: string;
}

export interface ResearchPriceLevel {
  price: number;
  label: string;
  source_block_id: string;
  ticker?: string;
}

interface ResearchBlockPosition {
  seq?: number;
  agent_id?: string;
  agent_label?: string;
}

export interface ResearchArtifact {
  artifact_id: string;
  kind: 'chart' | 'table' | 'image';
  title: string;
  dataset_refs?: string[];
  source_refs?: string[];
  spec?: {
    chart_type?: string;
    x?: string;
    series?: Array<{ field: string; name?: string; unit?: string }>;
    scale?: 'linear' | 'log';
    annotations?: Array<{ label?: string; start?: string | number; end?: string | number; value?: number }>;
  };
  data?: { rows?: Array<Record<string, unknown>>; panels?: Array<{ title: string; rows: Array<Record<string, unknown>>; chart_type?: string; baseline_included?: boolean; periods?: number }> };
  method?: Record<string, unknown>;
  limitations?: string[];
}

export interface ResearchAction {
  action_id: string;
  action: 'watchlist.add' | 'watchlist.remove';
  ticker: string;
  payload_hash: string;
  status: 'proposed' | 'completed' | 'cancelled' | 'expired';
  expires_at?: string;
}

export type ResearchBlock = ResearchBlockPosition & (
  | { id: string; kind: 'text'; content: string; revision: number; content_phase?: 'progress' | 'answer' }
  | { id: string; kind: 'reasoning'; content: string; provider?: string; revision: number;
      reasoning_kind?: string; truncated?: boolean; duration_ms?: number }
  | { id: string; kind: 'artifact'; artifact: ResearchArtifact; revision: number }
  | { id: string; kind: 'action'; action: ResearchAction; revision: number });

export interface ResearchStreamState {
  runId?: string;
  epoch?: string;
  seq: number;
  blocks: ResearchBlock[];
}

export interface ProviderReasoning {
  id: string;
  content: string;
  provider?: string;
}

