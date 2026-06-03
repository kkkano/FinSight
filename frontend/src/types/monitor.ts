/**
 * monitor.ts —— 工作台「Agent 盯盘中心」前端类型定义
 *
 * 对应后端 /api/monitor/* 契约（Phase 1）。
 * Finding（发现）= 工作台核心数据；MonitorTarget（盯盘对象）= 监控配置。
 */

/** 发现触发类型 */
export type FindingTriggerType =
  | 'price_move'        // 价格异动
  | 'concentration'     // 持仓集中度
  | 'sentiment_shift'   // 舆情突变
  | 'earnings_near'     // 财报临近
  | 'macro_event';      // 宏观事件

/** 发现处理状态 */
export type FindingStatus = 'new' | 'viewed' | 'acted';

/** 交易时段（后端 market_hours.py 对齐） */
export type MarketSession = 'pre_market' | 'regular' | 'after_hours' | 'closed';

/** 全部合法交易时段取值（运行时校验用） */
const MARKET_SESSIONS: readonly MarketSession[] = [
  'pre_market',
  'regular',
  'after_hours',
  'closed',
];

/**
 * 从 trigger_detail 提取交易时段标注。
 * 后端在 trigger_detail.market_session 写入时段；缺失或非法值（数字/乱字符串）返回 null。
 */
export function extractMarketSession(
  detail: Record<string, unknown>,
): MarketSession | null {
  const raw = detail?.market_session;
  if (typeof raw !== 'string') return null;
  return MARKET_SESSIONS.includes(raw as MarketSession)
    ? (raw as MarketSession)
    : null;
}

/** L2 agent 深析结果（Phase 2） */
export interface AgentAnalysis {
  /** agent 标识，如 technical_agent / risk_agent */
  agent: string;
  /** 分析摘要文本 */
  summary: string;
  /** 置信度（0~1）；agent 未评估时为 null（诚实原则，不编造） */
  confidence: number | null;
  /** 数据来源标签 */
  data_sources: string[];
  /** ISO 时间字符串 */
  analyzed_at: string;
}

/** 发现卡片上的行动按钮 */
export interface FindingAction {
  /** 行动类型，如 full_report / risk_review / rebalance 等 */
  type: string;
  /** 按钮文案 */
  label: string;
  /** 关联标的（可选，full_report 跳 Chat 时使用） */
  ticker?: string;
}

/** Finding（发现）—— Agent 主动盯盘发现的异常 */
export interface Finding {
  id: string;
  session_id: string;
  /** ISO 时间字符串 */
  created_at: string;
  /** 标的 ticker 或 "PORTFOLIO" */
  target: string;
  trigger_type: FindingTriggerType;
  /**
   * 触发明细，如 {"change_pct": -5.2, "threshold": 5.0}。
   * 可选字段 market_session?: MarketSession —— 后端交易时段感知写入（盘前/盘中/盘后/闭市），
   * 用 extractMarketSession 提取。
   */
  trigger_detail: Record<string, unknown>;
  /** 标题，如 "TSLA 单日下跌 5.2%" */
  title: string;
  /** 摘要 */
  summary: string;
  /** L2 agent 分析结果（Phase 2）；未分析时为 null */
  agent_analysis: AgentAnalysis | null;
  /** 可执行行动列表 */
  actions: FindingAction[];
  status: FindingStatus;
}

/** 盯盘对象类型 */
export type MonitorTargetType = 'holding' | 'watchlist' | 'custom';

/** MonitorTarget（盯盘对象）—— 监控规则配置 */
export interface MonitorTarget {
  id: string;
  session_id: string;
  type: MonitorTargetType;
  /** 标的 ticker，PORTFOLIO 级监控可为 null */
  ticker: string | null;
  /** 阈值配置，如 {"price_move_pct": 5.0, "concentration_pct": 80.0} */
  config: Record<string, number>;
  enabled: boolean;
  created_at: string;
}

/** GET /api/monitor/findings 响应 */
export interface FindingsResponse {
  findings: Finding[];
  count: number;
}

/** POST /api/monitor/scan 响应 */
export interface MonitorScanResponse {
  findings: Finding[];
  count: number;
}

/** GET /api/monitor/targets 响应 */
export interface MonitorTargetsResponse {
  targets: MonitorTarget[];
}

/** POST/PATCH /api/monitor/targets 单对象响应 */
export interface MonitorTargetResponse {
  target: MonitorTarget;
}

/** 创建盯盘对象入参 */
export interface CreateMonitorTargetParams {
  session_id: string;
  type: MonitorTargetType;
  ticker: string | null;
  config: Record<string, number>;
  enabled: boolean;
}

/** 更新盯盘对象入参（部分字段） */
export interface PatchMonitorTargetParams {
  config?: Record<string, number>;
  enabled?: boolean;
}
