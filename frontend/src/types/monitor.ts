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
  /** 触发明细，如 {"change_pct": -5.2, "threshold": 5.0} */
  trigger_detail: Record<string, unknown>;
  /** 标题，如 "TSLA 单日下跌 5.2%" */
  title: string;
  /** 摘要 */
  summary: string;
  /** L2 agent 分析结果，Phase 1 恒为 null */
  agent_analysis: Record<string, unknown> | null;
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
