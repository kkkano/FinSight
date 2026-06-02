import { describe, expect, it } from 'vitest';

import { parseSmartChartBlocks } from './SmartChart';

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
});
