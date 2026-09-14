import { describe, expect, it } from 'vitest';
import {
  injectChartMarkers,
  inferChartPeriod,
  inferChartValueMode,
  parseChartMarkers,
  shouldGenerateChart,
} from './chartIntent';

describe('chart intent', () => {
  it.each([
    ['画一下 AAPL 的k线', 'AAPL'],
    ['NVDA 趋势图', 'NVDA'],
  ])('关键词回退能识别图表请求：%s', async (query, ticker) => {
    await expect(shouldGenerateChart(query)).resolves.toMatchObject({
      tickers: [ticker],
      chartType: 'line',
      valueMode: 'close',
    });
  });

  it('普通公司介绍不误判为图表请求', async () => {
    await expect(shouldGenerateChart('介绍下苹果公司')).resolves.toEqual({
      tickers: [],
      chartType: null,
    });
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
