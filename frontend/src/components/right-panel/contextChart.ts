import type { EChartsOption, SeriesOption } from 'echarts';
import type { KlineData } from '../../types';
import type { ResearchPriceLevel } from '../../types/runtime';

export function buildContextChart(rows: KlineData[], options: {
  line: boolean; dark: boolean; convention: 'cn' | 'intl';
  priceLevels?: ResearchPriceLevel[]; earningsDates?: string[]; ma20?: Array<number | null>;
  expanded?: boolean;
}): EChartsOption | null {
  if (!rows.length) return null;
  const { line, dark, convention } = options;
  const green = dark ? '#3fc488' : '#12a05c';
  const red = dark ? '#ff6b72' : '#d9363e';
  const up = convention === 'cn' ? red : green;
  const down = convention === 'cn' ? green : red;
  const text = dark ? '#939bab' : '#5c6879';
  const grid = dark ? 'rgba(255,255,255,.07)' : 'rgba(15,23,42,.08)';
  const violet = dark ? '#ad91ff' : '#6741d9';
  const labels = rows.map((row) => row.time.slice(0, 10));
  const volume = rows.some((row) => typeof row.volume === 'number');
  const ma20 = options.ma20 ?? movingAverage20(rows);
  const levels = (options.priceLevels ?? []).filter((level) => Number.isFinite(level.price) && level.source_block_id);
  const markers = [...levels.map((level) => ({ yAxis: level.price, lineStyle: { color: violet, type: 'dashed' as const },
    label: { formatter: `${level.price} ${level.label}`, position: 'insideEndTop' as const, color: '#fff', backgroundColor: violet, borderRadius: 4, padding: [2, 4] } })),
    ...(options.earningsDates ?? []).filter((date) => labels.includes(date.slice(0, 10))).map((date) => ({ xAxis: date.slice(0, 10),
      lineStyle: { color: text, type: 'dashed' as const }, label: { formatter: '财报', color: text, position: 'insideEndTop' as const } }))];
  const series: SeriesOption[] = [{
    name: line ? '收盘价' : '日线', type: line ? 'line' : 'candlestick',
    data: line ? rows.map((row) => row.close) : rows.map((row) => [row.open, row.close, row.low, row.high]),
    ...(line ? { symbol: 'none', lineStyle: { width: 1.6, color: dark ? '#8098ff' : '#3b5bdb' } }
      : { itemStyle: { color: up, color0: down, borderColor: up, borderColor0: down } }),
    ...(markers.length ? { markLine: { symbol: ['none', 'none'], silent: true, data: markers } } : {}),
  } as SeriesOption];
  if (ma20.some((value) => value !== null)) series.push({ name: '20 日均线', type: 'line', data: ma20,
    symbol: 'none', connectNulls: false, lineStyle: { width: 1.4, color: dark ? '#f2a74b' : '#a85400' } });
  if (volume) series.push({ name: '成交量', type: 'bar', xAxisIndex: 1, yAxisIndex: 1,
    data: rows.map((row) => ({ value: row.volume ?? null, itemStyle: { color: row.close >= row.open ? up : down, opacity: .35 } })) });
  return { animation: false, grid: [{ left: 0, right: 50, top: 8, bottom: volume ? (options.expanded ? '28%' : 67) : 24 },
    ...(volume ? [{ left: 0, right: 50, height: options.expanded ? '18%' : 38, bottom: 24 }] : [])],
    tooltip: { trigger: 'axis', renderMode: 'richText', confine: true },
    xAxis: [{ type: 'category', data: labels, boundaryGap: !line,
      axisLine: { lineStyle: { color: grid } }, axisTick: { show: false }, axisLabel: { show: !volume, color: text, fontSize: 10 } },
      ...(volume ? [{ type: 'category' as const, data: labels, gridIndex: 1, axisLine: { show: false }, axisTick: { show: false },
        axisLabel: { color: text, fontSize: 10, formatter: (value: string) => value.slice(5).replace('-', '/') } }] : [])],
    yAxis: [{ scale: true, position: 'right', axisLabel: { color: text, fontSize: 10, fontFamily: 'JetBrains Mono Variable, monospace' },
      splitLine: { lineStyle: { color: grid } } }, ...(volume ? [{ gridIndex: 1, show: false }] : [])],
    dataZoom: [{ type: 'inside', xAxisIndex: volume ? [0, 1] : [0], filterMode: 'none' }], series };
}

export function movingAverage20(rows: KlineData[]): Array<number | null> {
  return rows.map((_row, index) => index < 19 ? null : rows.slice(index - 19, index + 1).reduce((total, row) => total + row.close, 0) / 20);
}
