/**
 * monitorThresholds.ts —— 监控阈值字段定义 + 纯函数校验
 *
 * 与后端契约对齐（PATCH /api/monitor/targets/{id}，超范围 422）：
 * - ticker 级：price_move_pct / sentiment_abs_threshold / earnings_near_days
 * - PORTFOLIO 级（集中度）：concentration_pct / macro_event_days
 *
 * 校验逻辑抽成纯函数，便于单测且保证前后端范围一致。
 */
import type { MonitorTarget } from '../../types/monitor';

/** 单个阈值字段的元数据（用于渲染表单 + 校验） */
export interface ThresholdFieldSpec {
  /** config 字段 key */
  key: string;
  /** 中文标签 */
  label: string;
  /** 单位后缀（如 % / 天），无单位为空字符串 */
  suffix: string;
  /** 允许的最小值（含） */
  min: number;
  /** 允许的最大值（含） */
  max: number;
  /** 输入步进；整数字段用 1，小数字段用 'any' */
  step: number | 'any';
  /** 是否要求整数 */
  integer: boolean;
}

/** ticker 级监控可编辑的阈值字段 */
export const TICKER_THRESHOLD_FIELDS: readonly ThresholdFieldSpec[] = [
  { key: 'price_move_pct', label: '价格异动阈值', suffix: '%', min: 0.1, max: 100, step: 'any', integer: false },
  { key: 'sentiment_abs_threshold', label: '舆情突变阈值', suffix: '', min: 0.05, max: 1.0, step: 'any', integer: false },
  { key: 'earnings_near_days', label: '财报临近天数', suffix: '天', min: 1, max: 30, step: 1, integer: true },
];

/** PORTFOLIO 级（集中度）监控可编辑的阈值字段 */
export const PORTFOLIO_THRESHOLD_FIELDS: readonly ThresholdFieldSpec[] = [
  { key: 'concentration_pct', label: '集中度阈值', suffix: '%', min: 1, max: 100, step: 'any', integer: false },
  { key: 'macro_event_days', label: '宏观事件天数', suffix: '天', min: 1, max: 30, step: 1, integer: true },
];

/**
 * 根据 target 选择该展示哪组阈值字段。
 * ticker 为 null（PORTFOLIO 级集中度目标）→ 集中度字段组；否则 → ticker 字段组。
 */
export function resolveThresholdFields(
  target: Pick<MonitorTarget, 'ticker'>,
): readonly ThresholdFieldSpec[] {
  return target.ticker ? TICKER_THRESHOLD_FIELDS : PORTFOLIO_THRESHOLD_FIELDS;
}

/** 校验结果 */
export interface ValidateThresholdResult {
  valid: boolean;
  /** field key → 中文错误信息 */
  errors: Record<string, string>;
}

/**
 * 校验阈值配置是否落在合法范围内（纯函数）。
 *
 * 规则：
 * - 只校验 config 中实际出现的字段（部分更新友好）。
 * - 已知字段（ticker / PORTFOLIO 两组并集）按各自范围校验；
 *   未知字段不报错（透传给后端，前端不越权拦截）。
 * - 非有限数 / 超范围 / 应为整数却带小数 → 记错误。
 */
export function validateThresholdConfig(
  config: Record<string, number>,
): ValidateThresholdResult {
  const specByKey = new Map<string, ThresholdFieldSpec>();
  for (const spec of [...TICKER_THRESHOLD_FIELDS, ...PORTFOLIO_THRESHOLD_FIELDS]) {
    specByKey.set(spec.key, spec);
  }

  const errors: Record<string, string> = {};

  for (const [key, value] of Object.entries(config)) {
    const spec = specByKey.get(key);
    if (!spec) continue; // 未知字段透传，不拦截

    if (typeof value !== 'number' || !Number.isFinite(value)) {
      errors[key] = `${spec.label}必须是数字`;
      continue;
    }
    if (spec.integer && !Number.isInteger(value)) {
      errors[key] = `${spec.label}必须是整数`;
      continue;
    }
    if (value < spec.min || value > spec.max) {
      errors[key] = `${spec.label}需在 ${spec.min}~${spec.max}${spec.suffix} 之间`;
    }
  }

  return { valid: Object.keys(errors).length === 0, errors };
}
