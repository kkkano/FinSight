import { describe, expect, it } from 'vitest';

import {
  buildLineOption,
  buildCandlestickOption,
  buildPriceVolumeOption,
  buildKlineSmartChartData,
  formatSmartChartValue,
  getRenderableMessageContent,
  getSmartChartProvenance,
  getSmartChartRenderer,
  isPriceLikeInlineBlock,
  parseSmartChartBlocks,
  resolveRealPriceChartRequest,
} from './SmartChart';
import { buildTerminalChartTheme } from '../hooks/useChartTheme';
import { applyPredictionOverlay, buildPredictionAnnotations } from './charts/PredictionOverlay';
import {
  loadPredictionOverlay,
  normalizePredictionOverlay,
  type PredictionOverlay,
} from '../types/chartPrediction';

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

  it('routes inline price semantics to the real market-data channel', () => {
    const [block] = parseSmartChartBlocks(
      '<chart type="candlestick" symbol="AAPL" title="Price">{"labels":["D1"],"ohlc":[[1,2,0.5,2.5]]}</chart>',
    );

    expect(isPriceLikeInlineBlock(block)).toBe(true);
    expect(resolveRealPriceChartRequest(block, [])).toEqual({ ticker: 'AAPL', chartType: 'candlestick', valueMode: 'close' });
  });

  it('normalizes price aliases and never trusts their inline arrays', () => {
    const [block] = parseSmartChartBlocks(
      '<chart type="line_price" ticker="NVDA" title="Price">{"labels":["D1"],"values":[999999]}</chart>',
    );

    expect(block).toMatchObject({ type: 'line', priceLike: true, symbol: 'NVDA' });
    expect(resolveRealPriceChartRequest(block, ['AAPL'])).toEqual({ ticker: 'NVDA', chartType: 'line', valueMode: 'close' });
  });

  it('treats a plain line with a price title as real market data', () => {
    const [block] = parseSmartChartBlocks(
      '<chart type="line" ticker="NVDA" title="价格走势">{"labels":["D1"],"values":[28.086951607]}</chart>',
    );

    expect(isPriceLikeInlineBlock(block)).toBe(true);
    expect(resolveRealPriceChartRequest(block, [])).toEqual({ ticker: 'NVDA', chartType: 'line', valueMode: 'close' });
  });

  it('treats an exact currency unit as price semantics but does not misclassify financial units', () => {
    const [priceBlock] = parseSmartChartBlocks(
      '<chart type="line" title="NVDA">{"unit":"USD","labels":["D1"],"values":[100]}</chart>',
    );
    const [revenueBlock] = parseSmartChartBlocks(
      '<chart type="line" title="Revenue">{"unit":"USD bn","labels":["2026"],"values":[100]}</chart>',
    );

    expect(isPriceLikeInlineBlock(priceBlock)).toBe(true);
    expect(isPriceLikeInlineBlock(revenueBlock)).toBe(false);
  });

  it('does not reroute a non-price indicator line', () => {
    const [block] = parseSmartChartBlocks(
      '<chart type="line" title="RSI 趋势">{"unit":"点","labels":["D1"],"values":[62.123456]}</chart>',
    );

    expect(isPriceLikeInlineBlock(block)).toBe(false);
  });

  it('keeps conceptual inline charts but marks their provenance as synthetic', () => {
    const [block] = parseSmartChartBlocks(
      '<chart type="pie" title="Concept">{"labels":["A"],"values":[1]}</chart>',
    );

    expect(isPriceLikeInlineBlock(block)).toBe(false);
    expect(getSmartChartProvenance(block)).toMatchObject({ synthetic: true, source: undefined });
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

describe('shared real-market chart adapter', () => {
  const rows = [
    { time: '2026-07-10', open: 100, close: 102, low: 99, high: 103, volume: 10 },
    { time: '2026-07-11', open: 102, close: 105, low: 101, high: 106, volume: 20 },
  ];

  it('feeds the same labels/OHLC contract to inline and SmartChart renderers', () => {
    expect(buildKlineSmartChartData(rows)).toEqual({
      labels: ['2026-07-10', '2026-07-11'],
      values: [102, 105],
      ohlc: [[100, 102, 99, 103], [102, 105, 101, 106]],
      volume: [10, 20],
    });
    expect(buildKlineSmartChartData(rows, 'return').values[1]).toBeCloseTo(2.941176, 5);
  });
});

describe('line chart number formatting', () => {
  it('renders currency and percentage values with bounded precision', () => {
    expect(formatSmartChartValue(28.086951607, '$')).toBe('$28.09');
    expect(formatSmartChartValue(28.086951607, '%')).toBe('28.09%');
  });

  it('uses the formatted value in the line tooltip instead of raw floating point output', () => {
    const option = buildLineOption(
      { labels: ['2026-07-10'], values: [28.086951607], unit: '$' },
      '价格走势',
      buildTerminalChartTheme(false),
    );
    const formatter = option.tooltip.formatter;
    const tooltip = formatter([{ axisValue: '2026-07-10', value: 28.086951607, marker: '', seriesName: 'Close' }]);

    expect(tooltip).toContain('$28.09');
    expect(tooltip).not.toContain('28.086951607');
  });

  it('does not force real price lines to start at zero', () => {
    const option = buildLineOption(
      { labels: ['2026-07-10', '2026-07-11'], values: [208.5, 212.4], unit: '$' },
      '价格走势',
      buildTerminalChartTheme(false),
    );

    expect(option.yAxis.scale).toBe(true);
  });
});

describe('行情图日期与缩放布局', () => {
  it('一年行情使用横向月日标签，并让日期轴与缩放条分别占位', () => {
    const labels = Array.from({ length: 252 }, (_, index) => (
      new Date(Date.UTC(2026, 0, 1 + index)).toISOString().slice(0, 10)
    ));
    const option = buildCandlestickOption(
      { labels, values: Array(252).fill(102), ohlc: Array(252).fill([100, 102, 99, 103]) },
      'AAPL 日线行情',
      buildTerminalChartTheme(true),
    );

    expect(option?.xAxis.axisLabel).toMatchObject({ rotate: 0, interval: 'auto', hideOverlap: true, fontSize: 12 });
    expect(option?.xAxis.axisLabel.formatter?.('2026-07-10')).toBe('07-10');
    expect(option?.xAxis.axisLabel.formatter?.('2026-07-11')).toBe('07-11');
    expect(option?.grid.bottom).toBeGreaterThan(50);
    expect(option?.dataZoom?.[1]).toMatchObject({ height: 22, showDetail: false });
    expect(option?.tooltip.confine).toBe(true);
    expect(option?.animation).toBe(false);
  });

  it('短时间窗口显示月日，真实日期和 OHLC 数据保持完整', () => {
    const data = {
      labels: ['2026-07-10', '2026-07-11'],
      values: [102, 105],
      ohlc: [[100, 102, 99, 103], [102, 105, 101, 106]] as [number, number, number, number][],
    };
    const option = buildCandlestickOption(data, 'AAPL 日线行情', buildTerminalChartTheme(false));

    expect(option?.xAxis.axisLabel.formatter?.('2026-07-10')).toBe('07-10');
    expect(option?.xAxis.data).toBe(data.labels);
    expect(option?.series[0].data).toBe(data.ohlc);
    expect(option?.dataZoom).toBeUndefined();
  });

  it('成交量从零起、使用紧凑刻度，并在紧邻价格的副图稳定显示', () => {
    const labels = Array.from({ length: 252 }, (_, index) => (
      new Date(Date.UTC(2026, 0, 1 + index)).toISOString().slice(0, 10)
    ));
    const volume = Array(252).fill(60_000_000);
    const option = buildPriceVolumeOption(
      { labels, values: Array(252).fill(102), ohlc: Array(252).fill([100, 102, 99, 103]), volume },
      'AAPL 日线行情',
      buildTerminalChartTheme(true),
    );
    const volumeAxis = option?.yAxis[1];
    const formatter = volumeAxis?.axisLabel.formatter;

    expect(volumeAxis).toMatchObject({ min: 0, scale: false, splitNumber: 2, name: '成交量' });
    expect(typeof formatter).toBe('function');
    if (typeof formatter !== 'function') throw new Error('成交量刻度格式化器缺失');
    expect(formatter(60_000_000)).toBe('60M');
    expect(formatter(0)).toBe('0');
    expect(option?.grid).toMatchObject([{ bottom: '36%' }, { top: '68%', bottom: 66 }]);
    expect(option?.animation).toBe(false);
    expect(option?.series[1].data).toBe(volume);
    expect(option?.series[1].itemStyle).toMatchObject({ opacity: 0.55 });
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

describe('prediction overlay isolation', () => {
  const rawPrediction = {
    prediction_id: 'pred-1',
    symbol: 'AAPL',
    direction: 'long',
    anchor: { timeframe: '1d', time: '2026-07-10', price: 103 },
    entry: 104,
    stop: 98,
    target1: 112,
    target2: 118,
    status: 'open',
    bars: [{ close: 999999 }],
    series: [{ data: [999999] }],
    data: [999999],
  };

  it('drops prediction-provided market arrays and keeps every real series data item immutable', () => {
    const first = normalizePredictionOverlay(rawPrediction, 'AAPL');
    const second = normalizePredictionOverlay({ ...rawPrediction, prediction_id: 'pred-2', entry: 106 }, 'AAPL');
    expect(first).not.toBeNull();
    expect(second).not.toBeNull();
    expect(first).not.toHaveProperty('bars');
    expect(first).not.toHaveProperty('series');
    expect(first).not.toHaveProperty('data');

    const candleData = [[100, 101, 99, 102], [101, 103, 100, 104]];
    const volumeData = [1000, 1200];
    const marketOption = {
      series: [
        { name: '真实 K 线', type: 'candlestick', data: candleData },
        { name: '真实成交量', type: 'bar', data: volumeData },
      ],
    };
    const labels = ['2026-07-09', '2026-07-10'];
    const firstOption = applyPredictionOverlay(marketOption, first, labels);
    const secondOption = applyPredictionOverlay(marketOption, second, labels);

    expect(firstOption.series?.map((series) => series.data)).toEqual([candleData, volumeData]);
    expect(secondOption.series?.map((series) => series.data)).toEqual([candleData, volumeData]);
    expect(firstOption.series?.[0]?.data).toBe(candleData);
    expect(secondOption.series?.[0]?.data).toBe(candleData);
    expect(firstOption.series?.[0]?.markLine).not.toEqual(secondOption.series?.[0]?.markLine);
  });

  it('anchors exactly by time and emits price lines plus neutral/zones areas', () => {
    const prediction: PredictionOverlay = {
      predictionId: 'pred-neutral',
      symbol: 'AAPL',
      direction: 'neutral',
      anchor: { timeframe: '1d', time: '2026-07-10', price: 103 },
      entry: 104,
      stop: 98,
      target1: 112,
      target2: 118,
      range: { low: 99, high: 108 },
      zones: [{ low: 101, high: 102, label: '观察区' }],
      status: 'invalidated',
    };
    const annotations = buildPredictionAnnotations(prediction, ['7/9/2026', '7/10/2026', '7/11/2026']);
    const markPoint = annotations.markPoint as { data: Array<{ coord: [string, number] }> };
    const markLine = annotations.markLine as { data: Array<{ label: { formatter: string }; lineStyle: { type: string } }> };
    const markArea = annotations.markArea as { data: unknown[] };

    expect(markPoint.data[0]?.coord).toEqual(['7/10/2026', 103]);
    expect(markLine.data.map((line) => line.label.formatter)).toEqual([
      '入场 104 · 已失效',
      '止损 98 · 已失效',
      'T1 112 · 已失效',
      'T2 118 · 已失效',
    ]);
    expect(markLine.data.every((line) => line.lineStyle.type === 'dashed')).toBe(true);
    expect(markArea.data).toHaveLength(3);
  });

  it('日线日期不会因 UTC 零点转换到本地时区而移动到前一天', () => {
    const prediction = normalizePredictionOverlay(rawPrediction, 'AAPL');
    expect(prediction).not.toBeNull();
    const annotations = buildPredictionAnnotations(prediction!, ['7/9/2026', '7/10/2026', '7/11/2026']);
    const markPoint = annotations.markPoint as { data: Array<{ coord: [string, number] }> };

    expect(markPoint.data[0]?.coord).toEqual(['7/10/2026', 103]);
  });

  it('带时间戳的锚点继续使用本地日期匹配行情标签', () => {
    const localNoon = new Date(2026, 6, 10, 12);
    const prediction = normalizePredictionOverlay({
      ...rawPrediction,
      anchor: { ...rawPrediction.anchor, time: localNoon.toISOString() },
    }, 'AAPL');
    expect(prediction).not.toBeNull();
    const annotations = buildPredictionAnnotations(prediction!, ['7/9/2026', '7/10/2026', '7/11/2026']);
    const markPoint = annotations.markPoint as { data: Array<{ coord: [string, number] }> };

    expect(markPoint.data[0]?.coord).toEqual(['7/10/2026', 103]);
  });

  it('degrades 404, unauthorized and symbol-mismatch responses without an overlay', async () => {
    await expect(loadPredictionOverlay('missing', 'AAPL', async () => {
      throw new Error('404');
    })).resolves.toEqual({ status: 'unavailable', overlay: null });

    await expect(loadPredictionOverlay('other-user', 'AAPL', async () => ({
      ...rawPrediction,
      symbol: 'MSFT',
    }))).resolves.toEqual({ status: 'unavailable', overlay: null });
  });
});
