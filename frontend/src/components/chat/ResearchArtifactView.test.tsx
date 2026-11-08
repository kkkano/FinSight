import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { artifactColumnLabel, artifactMethodRows, artifactValueLabel, buildArtifactChart, buildArtifactPanels, normalizeArtifactAnnotations, ResearchArtifactView } from './ResearchArtifactView';
import type { ResearchArtifact } from '../../types/runtime';

const artifact: ResearchArtifact = {
  artifact_id: 'test', title: '价格', kind: 'chart',
  spec: { chart_type: 'line', x: 'date', series: [{ field: 'close', unit: 'USD' }] },
  data: { rows: [{ date: '2026-01-01', close: 10 }, { date: '2026-01-02', close: null }] },
};
describe('research artifact chart contract', () => {
  it('keeps absent values absent instead of fabricating zero', () => {
    const option = buildArtifactChart(artifact, false) as any;
    expect(option.series[0].data).toEqual([10, null]);
    expect(option.series[0].connectNulls).toBe(false);
  });
  it('uses a declarative renderer and never executes a model-supplied formatter', () => {
    const supplied = { ...artifact, spec: { ...artifact.spec!, formatter: 'malicious()' } };
    const option = buildArtifactChart(supplied, false) as any;
    expect(option.tooltip.renderMode).toBe('richText');
    expect(option.tooltip.formatter).toBeUndefined();
    expect(JSON.stringify(option)).not.toContain('malicious');
  });
  it('preserves the selected market color convention for candles', () => {
    const candle = { ...artifact, spec: { ...artifact.spec!, chart_type: 'candlestick' } };
    const international = buildArtifactChart(candle, false, 'intl') as any;
    const chinese = buildArtifactChart(candle, false, 'cn') as any;
    expect(chinese.series[0].itemStyle.color).toBe(international.series[0].itemStyle.color0);
  });
  it('does not build a placeholder chart without rows', () => {
    expect(buildArtifactChart({ ...artifact, data: { rows: [] } }, false)).toBeNull();
  });
  it('renders at most six real-data small multiples and never manufactures OHLC', () => {
    const rows = [{ date: '2026-01-01', close: 10 }, { date: '2026-01-02', close: 9 }];
    const panels = buildArtifactPanels({ ...artifact, data: { rows, panels: Array.from({ length: 8 }, (_, i) => ({
      title: '区间 ' + i, chart_type: 'candlestick', rows,
    })) } }, false);
    expect(panels).toHaveLength(6);
    expect((panels[0].option as any).series[0].type).toBe('line');
    expect((panels[0].option as any).series[0].data).toEqual([10, 9]);
  });
  it('uses candles when a panel includes all actual OHLC fields', () => {
    const rows = [{ date: '2026-01-01', open: 9, close: 10, low: 8, high: 11 }];
    const panels = buildArtifactPanels({ ...artifact, data: { rows, panels: [{ title: '区间', chart_type: 'candlestick', rows }] } }, false);
    expect((panels[0].option as any).series[0].data).toEqual([[9, 10, 8, 11]]);
  });

  it('counts actual chart sources once and keeps derived tool records out of the footer', () => {
    const sources = [{ source_id: 'S1', title: 'twelve_data', source: 'twelve_data', as_of: '2026-11-06T00:00:00Z' },
      { source_id: 'S2', title: 'get_stock_historical_data', source: 'get_stock_historical_data' },
      { source_id: 'S3', title: 'market_chart' }, { source_id: 'S4', source: 'twelve_data' }, { source_id: 'S5', source: 'analyze_dataset' }];
    const visible = renderToStaticMarkup(<ResearchArtifactView artifact={{ ...artifact, source_refs: sources.map((source) => source.source_id) }} sources={sources} />)
      .replace(/<[^>]+>/g, '');
    expect(visible).toContain('Twelve Data');
    expect(visible).toContain('1 个数据来源');
    expect(visible).toContain('2026-11-06');
    expect(visible).not.toMatch(/历史行情数据|数据分析结果|2026-11-06T/);
    expect(visible).not.toMatch(/twelve_data|market_chart|get_stock/);
  });

  it('aligns date-only annotations to the actual ISO categories, including the ending day', () => {
    const labels = ['2026-10-01T00:00:00+00:00', '2026-10-08T00:00:00+00:00', '2026-10-15T00:00:00+00:00'];
    const annotations = [{ start: '2026-10-01', end: '2026-10-15', label: '区间' }];
    expect(normalizeArtifactAnnotations(annotations, labels)).toEqual([{ start: labels[0], end: labels[2], label: '区间' }]);
    expect(annotations[0].end).toBe('2026-10-15');
    const panels = buildArtifactPanels({ ...artifact, spec: { ...artifact.spec!, annotations }, data: {
      panels: [{ title: '区间', baseline_included: true, periods: 2, rows: labels.map((date, index) => ({ date, close: 10 - index })) }],
    } }, false);
    expect(panels[0]).toMatchObject({ baselineIncluded: true, periods: 2 });
    expect((panels[0].option as any).series[0].markArea.data[0]).toMatchObject([{ name: '区间1', xAxis: labels[0] }, { xAxis: labels[2] }]);
    expect((panels[0].option as any).series[0].data).toEqual([10, 9, 8]);
    expect((panels[0].option as any).yAxis.type).toBe('value');
    expect((panels[0].option as any).series[0].markArea.label.show).toBe(false);
    expect((panels[0].option as any).xAxis.axisLabel.interval(0)).toBe(true);
    expect((panels[0].option as any).xAxis.axisLabel.interval(1)).toBe(false);
    expect((panels[0].option as any).xAxis.axisLabel.interval(2)).toBe(true);
  });

  it('includes a whole day only for date boundaries and preserves intraday time precision', () => {
    const labels = ['2026-10-01T09:30:00Z', '2026-10-01T13:00:00Z', '2026-10-01T15:30:00Z', '2026-10-02T09:30:00Z'];
    expect(normalizeArtifactAnnotations([{ start: '2026-10-01', end: '2026-10-01' }], labels))
      .toEqual([{ start: labels[0], end: labels[2] }]);
    expect(normalizeArtifactAnnotations([{ start: '2026-10-01T10:00:00Z', end: '2026-10-01T14:00:00Z' }], labels))
      .toEqual([{ start: labels[1], end: labels[1] }]);
    expect(normalizeArtifactAnnotations([{ start: '2025-01-01', end: '2025-01-02' }], labels)).toEqual([]);
  });

  it('labels known metadata and percentage series without changing numeric values or unknown treatment', () => {
    const comparison = { ...artifact, spec: { ...artifact.spec!, series: [{ field: 'series_2', name: 'AMD', unit: '%' }] } };
    expect(artifactColumnLabel(comparison, 'series_2')).toBe('AMD（%）');
    expect(artifactColumnLabel(comparison, 'as_of')).toBe('数据时间');
    expect(artifactValueLabel('series_2', 109.67501354127754)).toBe('109.67501354127754');
    expect(artifactValueLabel('source', 'twelve_data')).toBe('Twelve Data');
    expect(artifactMethodRows({ price_basis: 'unknown', dividends_included: null, frequency: 'weekly' })).toEqual([
      { label: '价格口径', value: '未注明' }, { label: '是否计入股息', value: '未注明' }, { label: '频率', value: '周线' },
    ]);
  });

  it('numbers event windows while keeping complete labels in tooltips and local panels on linear axes', () => {
    const rows = [{ date: '2026-10-01', close: 100 }, { date: '2026-10-02', close: 90 }, { date: '2026-10-03', close: 80 }];
    const source = { ...artifact, spec: { ...artifact.spec!, scale: 'log' as const,
      annotations: [{ start: '2026-10-01', end: '2026-10-02', label: '下跌1期 -10%' }, { start: '2026-10-02', end: '2026-10-03', label: '下跌1期 -11.1%' }] },
      data: { rows, panels: [{ title: '下跌1期 -10%', rows: rows.slice(0, 2) }] } };
    const option = buildArtifactChart(source, false) as any;
    expect(option.series[0].markArea.data.map((area: any[]) => area[0].name)).toEqual(['区间1', '区间2']);
    expect(option.series[0].markArea.data[0][0].tooltip.formatter).toContain('下跌1期 -10%');
    expect(option.tooltip.formatter([{ axisValue: '2026-10-01', seriesName: 'close', value: 100 }])).toContain('区间1 · 下跌1期 -10%');
    expect(option.yAxis.type).toBe('log');
    expect((buildArtifactPanels(source, false)[0].option as any).yAxis.type).toBe('value');
  });

});

