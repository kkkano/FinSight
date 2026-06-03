import { describe, expect, it } from 'vitest';

import {
  resolveThresholdFields,
  validateThresholdConfig,
  TICKER_THRESHOLD_FIELDS,
  PORTFOLIO_THRESHOLD_FIELDS,
} from './monitorThresholds';

describe('validateThresholdConfig', () => {
  it('通过：所有字段都在合法范围内', () => {
    const result = validateThresholdConfig({
      price_move_pct: 5,
      sentiment_abs_threshold: 0.35,
      earnings_near_days: 3,
      concentration_pct: 80,
      macro_event_days: 2,
    });
    expect(result.valid).toBe(true);
    expect(Object.keys(result.errors)).toHaveLength(0);
  });

  it('报错：价格异动超上限（>100）', () => {
    const result = validateThresholdConfig({ price_move_pct: 150 });
    expect(result.valid).toBe(false);
    expect(result.errors.price_move_pct).toContain('价格异动阈值');
  });

  it('报错：价格异动低于下限（<0.1）', () => {
    const result = validateThresholdConfig({ price_move_pct: 0.05 });
    expect(result.valid).toBe(false);
    expect(result.errors.price_move_pct).toBeTruthy();
  });

  it('报错：舆情突变阈值超出 0.05~1.0', () => {
    const tooHigh = validateThresholdConfig({ sentiment_abs_threshold: 1.5 });
    expect(tooHigh.valid).toBe(false);
    const tooLow = validateThresholdConfig({ sentiment_abs_threshold: 0.01 });
    expect(tooLow.valid).toBe(false);
  });

  it('报错：财报临近天数必须是整数', () => {
    const result = validateThresholdConfig({ earnings_near_days: 3.5 });
    expect(result.valid).toBe(false);
    expect(result.errors.earnings_near_days).toContain('整数');
  });

  it('报错：集中度阈值超出 1~100', () => {
    const result = validateThresholdConfig({ concentration_pct: 0 });
    expect(result.valid).toBe(false);
    expect(result.errors.concentration_pct).toBeTruthy();
  });

  it('报错：宏观事件天数超出 1~30', () => {
    const result = validateThresholdConfig({ macro_event_days: 60 });
    expect(result.valid).toBe(false);
    expect(result.errors.macro_event_days).toBeTruthy();
  });

  it('报错：非有限数', () => {
    const result = validateThresholdConfig({ price_move_pct: Number.NaN });
    expect(result.valid).toBe(false);
    expect(result.errors.price_move_pct).toContain('数字');
  });

  it('未知字段透传不拦截', () => {
    const result = validateThresholdConfig({ some_unknown_field: 999 } as Record<string, number>);
    expect(result.valid).toBe(true);
  });

  it('边界值（min / max 含端点）通过', () => {
    expect(validateThresholdConfig({ price_move_pct: 0.1 }).valid).toBe(true);
    expect(validateThresholdConfig({ price_move_pct: 100 }).valid).toBe(true);
    expect(validateThresholdConfig({ earnings_near_days: 1 }).valid).toBe(true);
    expect(validateThresholdConfig({ earnings_near_days: 30 }).valid).toBe(true);
  });
});

describe('resolveThresholdFields', () => {
  it('ticker 级目标 → ticker 字段组', () => {
    const fields = resolveThresholdFields({ ticker: 'AAPL' });
    expect(fields).toBe(TICKER_THRESHOLD_FIELDS);
    expect(fields.map((f) => f.key)).toContain('price_move_pct');
  });

  it('PORTFOLIO 级目标（ticker=null）→ 集中度字段组', () => {
    const fields = resolveThresholdFields({ ticker: null });
    expect(fields).toBe(PORTFOLIO_THRESHOLD_FIELDS);
    expect(fields.map((f) => f.key)).toContain('concentration_pct');
  });
});
