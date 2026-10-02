export type PredictionType = 'direction' | 'drawdown';
export type PredictionDirection = 'up' | 'down' | 'flat';

export interface PredictionGroup {
  agent: string;
  prediction_type: PredictionType;
  actual_model: string;
  model_confirmed: boolean;
  prompt_version: string;
  strategy_version: string;
  scorer_version: string;
  n: number;
  hits: number;
  hit_rate: number | null;
  baseline_hits: number;
  baseline_hit_rate: number | null;
  delta: number | null;
  tp: number;
  fp: number;
  tn: number;
  fn: number;
}

export interface PredictionRecord {
  id: string;
  ticker: string;
  agent: string;
  prediction_type: PredictionType;
  batch_date: string;
  status: string;
  direction: PredictionDirection | null;
  event_occurs: boolean | null;
  reason: string;
  evidence_refs: string[];
  issued_at: string | null;
  window_start: string;
  window_end: string;
  actual_model: string;
  model_confirmed: boolean;
  prompt_version: string;
  outcome: null | {
    p0: number;
    p5: number;
    return_pct: number;
    max_drawdown: number;
    actual_direction: string;
    actual_event: boolean;
    hit: boolean;
    baseline_hit: boolean;
    source: string;
    settled_at: string;
  };
  error_code: string | null;
}

export interface PredictionTrackRecord {
  enabled: boolean;
  universe: { version: string; tickers: string[] };
  coverage: {
    batch_date: string | null;
    expected: number;
    accepted: number;
    counts: Record<string, number>;
    attempts: number;
    last_update: string | null;
  };
  summary: {
    opportunities: number;
    predictions: number;
    settled: number;
    pending: number;
    failed: number;
    missed: number;
    abstained: number;
    awaiting_data: number;
    queued?: number;
    running?: number;
    interrupted?: number;
    batch_count: number;
    stock_count: number;
  };
  groups: PredictionGroup[];
  records: PredictionRecord[];
  pagination?: {
    offset: number;
    limit: number;
    total: number;
    has_more: boolean;
  };
  metadata: {
    source: string;
    horizon_sessions: number;
    direction_threshold: number;
    drawdown_threshold: number;
  };
}
