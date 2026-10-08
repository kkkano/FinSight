import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

import { getPredictionDirectionPresentation, isTerminalPredictionStatus } from './predictionPresentation';
import { TechnicalSummaryCard } from '../components/dashboard/tabs/technical/TechnicalSummaryCard';

const render = (node: ReactNode) => renderToStaticMarkup(
  <QueryClientProvider client={new QueryClient()}>{node}</QueryClientProvider>,
);

describe('判断与技术状态口径', () => {
  it('回落假设写明条件，不把当前趋势直接称为看空', () => {
    const meaning = getPredictionDirectionPresentation('short', 'open');
    expect(meaning.label).toBe('AI 回落假设');
    expect(meaning.description).toContain('满足入场条件');
    expect(meaning.description).toContain('不代表当前技术趋势已转空');
    expect(meaning.historical).toBe(false);
  });

  it.each(['hit_target', 'hit_stop', 'invalidated', 'held_range', 'broke_range'])('已结束 %s 明确展示原判断', (status) => {
    expect(isTerminalPredictionStatus(status)).toBe(true);
    expect(getPredictionDirectionPresentation('long', status).label).toBe('原判断：上行假设');
  });

  it('未知和等待状态不伪造已结束', () => {
    expect(isTerminalPredictionStatus('data_pending')).toBe(false);
    expect(isTerminalPredictionStatus(null)).toBe(false);
  });

  it('趋势多数偏多且RSI超买时同时说明当前结构与回落风险', () => {
    const html = render(<TechnicalSummaryCard technicals={{ close: 333, ma5: 330, ma10: 320, ma20: 310, ma50: 300,
      ma100: 290, ma200: 280, ema12: 325, ema26: 315, rsi: 89.86, macd_hist: -1, stoch_k: 50, cci: 0, trend: 'bullish', momentum: 'bearish', support_levels: [], resistance_levels: [] }} />);
    expect(html).toContain('当前技术状态');
    expect(html).toContain('指标多数偏多');
    expect(html).toContain('不是未来涨跌预测');
    expect(html).toContain('短线回落风险');
    expect(html).toContain('偏弱');
    expect(html).not.toContain('买入:');
  });

  it('没有指标时展示数据不足，不伪造中性结论', () => {
    expect(render(<TechnicalSummaryCard />)).toContain('数据不足');
  });
});
