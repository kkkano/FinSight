import { afterEach, describe, expect, it, vi } from 'vitest';

import { apiClient } from '../api/client';
import {
  injectChartMarkers,
  inferChartPeriod,
  inferChartValueMode,
  isInlineChartRenderable,
  parseChartMarkers,
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
      valueMode: 'close',
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
      .toBe('已有\n\n[CHART:AAPL:line]\n\n[CHART:NVDA:line:return:1y]\n\n[CHART:MSFT:line:return:1y]');
  });

  it('价格走势图保留真实价格语义和用户时间范围', () => {
    expect(inferChartValueMode('NVDA 最近一个月价格走势图', 'line')).toBe('close');
    expect(inferChartPeriod('NVDA 最近一个月价格走势图')).toBe('1mo');
    const content = injectChartMarkers('', ['NVDA'], 'line', { valueMode: 'close', period: '1mo' });
    expect(content.trim()).toBe('[CHART:NVDA:line:close:1mo]');
    expect(parseChartMarkers(content)).toEqual([{
      ticker: 'NVDA',
      chartType: 'line',
      valueMode: 'close',
      period: '1mo',
    }]);
  });

  it('旧 marker 继续使用历史 return/1y 语义', () => {
    expect(parseChartMarkers('[CHART:AAPL:line]')).toEqual([{
      ticker: 'AAPL',
      chartType: 'line',
      valueMode: 'return',
      period: '1y',
    }]);
  });
});
