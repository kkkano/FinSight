import { describe, expect, it } from 'vitest';

import { getRenderableMessageContent, getSmartChartRenderer, parseSmartChartBlocks } from './SmartChart';

describe('parseSmartChartBlocks', () => {
  it('accepts extended chart types and caps smart charts at four per message', () => {
    const content = [
      '<chart type="bar" title="Revenue">{"labels":["Q1"],"values":[1]}</chart>',
      '<chart type="candlestick" title="Price">{"labels":["D1"],"values":[1],"ohlc":[[1,2,0.5,2.5]]}</chart>',
      '<chart type="scenario" title="Cases">{"labels":["Base"],"values":[3],"series":[{"name":"EPS","values":[3]}]}</chart>',
      '<chart_ref type="heatmap" source="technicals" fields="rsi,macd" title="Signals"/>',
      '<chart_ref type="radar" source="news" fields="market,impact" title="News"/>',
    ].join('\n');

    const blocks = parseSmartChartBlocks(content);

    expect(blocks).toHaveLength(4);
    expect(blocks.map((block) => block.type)).toEqual([
      'bar',
      'candlestick',
      'scenario',
      'heatmap',
    ]);
  });

  it('preserves a real-data as-of attribute on chart refs', () => {
    const [block] = parseSmartChartBlocks(
      '<chart_ref type="line" source="market_chart" fields="close" as_of="2026-07-12" title="Price"/>',
    );

    expect(block).toMatchObject({ mode: 'ref', source: 'market_chart', asOf: '2026-07-12' });
  });
});

describe('getSmartChartRenderer', () => {
  const denseData = { labels: Array.from({ length: 201 }, (_, index) => String(index)), values: [] };

  it('uses canvas for dense time-series charts', () => {
    expect(getSmartChartRenderer('line', denseData)).toBe('canvas');
    expect(getSmartChartRenderer('candlestick', { ...denseData, ohlc: Array(201).fill([1, 2, 0, 3]) })).toBe('canvas');
  });

  it('keeps compact and categorical charts on svg', () => {
    expect(getSmartChartRenderer('line', { labels: ['a'], values: [1] })).toBe('svg');
    expect(getSmartChartRenderer('bar', denseData)).toBe('svg');
    expect(getSmartChartRenderer('pie', denseData)).toBe('svg');
  });
});

describe('getRenderableMessageContent', () => {
  const content = [
    'streaming text',
    '[CHART:AAPL:line]',
    '<chart type="bar" title="Revenue">{"labels":["Q1"],"values":[1]}</chart>',
  ].join('\n');

  it('returns streaming content untouched so chart stripping is skipped per token', () => {
    expect(getRenderableMessageContent(content, true)).toBe(content);
  });

  it('removes chart markers after the message is finalized', () => {
    expect(getRenderableMessageContent(content, false)).toBe('streaming text');
  });
});
