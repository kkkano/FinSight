import { afterEach, describe, expect, it, vi } from 'vitest';

import { apiClient } from '../api/client';
import {
  injectChartMarkers,
  isInlineChartRenderable,
  shouldGenerateChart,
} from './chartIntent';

describe('chart intent', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it.each([
    ['画一下 AAPL 的k线', 'AAPL'],
    ['NVDA 趋势图', 'NVDA'],
  ])('关键词回退能识别图表请求：%s', async (query, ticker) => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    vi.spyOn(apiClient, 'detectChartType').mockRejectedValue(new Error('offline'));

    await expect(shouldGenerateChart(query)).resolves.toMatchObject({
      tickers: [ticker],
      chartType: 'line',
    });
  });

  it('普通公司介绍不误判为图表请求', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    vi.spyOn(apiClient, 'detectChartType').mockRejectedValue(new Error('offline'));

    await expect(shouldGenerateChart('介绍下苹果公司')).resolves.toEqual({
      tickers: [],
      chartType: null,
      smartChart: null,
    });
  });

  it('只允许 InlineChart 能真实表达的类型和数据源', () => {
    expect(isInlineChartRenderable('line', 'kline')).toBe(true);
    expect(isInlineChartRenderable('candlestick', 'technical')).toBe(true);
    expect(isInlineChartRenderable('pie', 'composition')).toBe(false);
    expect(isInlineChartRenderable('line', 'financial')).toBe(false);
  });

  it('注入图表标记时去重并限制最多三个 ticker', () => {
    expect(injectChartMarkers('已有\n\n[CHART:AAPL:line]', ['AAPL', 'NVDA', 'MSFT', 'TSLA'], 'line'))
      .toBe('已有\n\n[CHART:AAPL:line]\n\n[CHART:NVDA:line]\n\n[CHART:MSFT:line]');
  });
});
