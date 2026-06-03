import { describe, expect, it } from 'vitest';

import { shouldUseSmartChartData } from './ChatInput';

// shouldUseSmartChartData 决定某 (chartType, dataKind) 是否走 SmartChart 数据路径
// （pie/bar 的真实数据源接入）。这是图表智能化遗留收口的纯函数判断。
describe('shouldUseSmartChartData', () => {
  it('returns true for pie + composition（营收构成饼图）', () => {
    expect(shouldUseSmartChartData('pie', 'composition')).toBe(true);
  });

  it('returns true for bar + comparison（同行对比柱状图）', () => {
    expect(shouldUseSmartChartData('bar', 'comparison')).toBe(true);
  });

  it('returns false for kline 类图表（应走 InlineChart 而非 SmartChart 数据）', () => {
    expect(shouldUseSmartChartData('line', 'kline')).toBe(false);
    expect(shouldUseSmartChartData('candlestick', 'technical')).toBe(false);
  });

  it('returns false when chartType / dataKind 缺失', () => {
    expect(shouldUseSmartChartData(null, 'composition')).toBe(false);
    expect(shouldUseSmartChartData('pie', null)).toBe(false);
    expect(shouldUseSmartChartData(null, null)).toBe(false);
  });

  it('returns false for 类型与取数方式错配（pie 配 comparison / bar 配 composition 仍放行，但非白名单组合拒绝）', () => {
    // pie 是构成类、bar 是对比类——两者都在白名单内，交叉组合也允许（数据格式一致）。
    expect(shouldUseSmartChartData('pie', 'comparison')).toBe(true);
    expect(shouldUseSmartChartData('bar', 'composition')).toBe(true);
    // 但非白名单的 chartType / dataKind 一律拒绝。
    expect(shouldUseSmartChartData('scatter', 'composition')).toBe(false);
    expect(shouldUseSmartChartData('pie', 'financial')).toBe(false);
    expect(shouldUseSmartChartData('radar', 'financial')).toBe(false);
  });
});
