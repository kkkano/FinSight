/**
 * SmartChart - Renders LLM-generated `<chart>` and API-ref `<chart_ref>` tags.
 *
 * Two modes:
 * 1. `<chart type="bar" title="...">{"labels":[...],"values":[...]}</chart>`
 *    → LLM provides approximate data directly in JSON
 * 2. `<chart_ref type="bar" source="peers" fields="trailing_pe" title="PE对比"/>`
 *    → References real data from dashboardStore
 *
 * Graceful degradation: JSON parse failures or missing data → silent skip.
 */
import { useMemo } from 'react';
import ReactECharts from 'echarts-for-react';

import { useChartTheme, type ChartTheme } from '../hooks/useChartTheme';
import { useDashboardStore } from '../store/dashboardStore';
import type {
  ChartPoint,
  DashboardData,
  EarningsHistoryEntry,
  FinancialStatement,
  PeerMetrics,
  TechnicalData,
  ValuationData,
} from '../types/dashboard';

// --- Types ---

export type SmartChartType =
  | 'bar'
  | 'line'
  | 'pie'
  | 'scatter'
  | 'gauge'
  | 'candlestick'
  | 'price_volume'
  | 'rs_line'
  | 'waterfall'
  | 'heatmap'
  | 'radar'
  | 'valuation_band'
  | 'bubble'
  | 'drawdown'
  | 'scenario';

export interface SmartChartBlock {
  mode: 'inline' | 'ref';
  type: SmartChartType;
  title: string;
  /** For inline mode: raw JSON string */
  dataJson?: string;
  /** For ref mode */
  source?: string;
  fields?: string;
}

export type SmartChartOhlcPoint = [open: number, close: number, low: number, high: number];

export interface SmartChartSeries {
  name: string;
  values: number[];
  unit?: string;
}

export interface SmartChartBand {
  name: string;
  values: number[];
}

export interface SmartChartEvent {
  label: string;
  date?: string;
  index?: number;
  value?: number;
  kind?: string;
}

export interface SmartChartData {
  labels: string[];
  values: number[];
  unit?: string;
  series?: SmartChartSeries[];
  ohlc?: SmartChartOhlcPoint[];
  volume?: number[];
  bands?: SmartChartBand[];
  events?: SmartChartEvent[];
}

// --- Helpers ---

const VALID_TYPES = [
  'bar',
  'line',
  'pie',
  'scatter',
  'gauge',
  'candlestick',
  'price_volume',
  'rs_line',
  'waterfall',
  'heatmap',
  'radar',
  'valuation_band',
  'bubble',
  'drawdown',
  'scenario',
] as const satisfies readonly SmartChartType[];

const FINANCIAL_NUMERIC_FIELDS = [
  'revenue',
  'gross_profit',
  'operating_income',
  'net_income',
  'eps',
  'total_assets',
  'total_liabilities',
  'operating_cash_flow',
  'free_cash_flow',
] as const;

type FinancialNumericField = (typeof FINANCIAL_NUMERIC_FIELDS)[number];

const TECHNICAL_NUMERIC_FIELDS = [
  'close',
  'ma5',
  'ma10',
  'ma20',
  'ma50',
  'ma100',
  'ma200',
  'ema12',
  'ema26',
  'rsi',
  'macd',
  'macd_signal',
  'macd_hist',
  'stoch_k',
  'stoch_d',
  'adx',
  'cci',
  'williams_r',
  'bollinger_upper',
  'bollinger_middle',
  'bollinger_lower',
  'avg_volume',
] as const;

type TechnicalNumericField = (typeof TECHNICAL_NUMERIC_FIELDS)[number];

const PEER_NUMERIC_FIELDS = [
  'trailing_pe',
  'forward_pe',
  'price_to_book',
  'ev_to_ebitda',
  'net_margin',
  'roe',
  'revenue_growth',
  'dividend_yield',
  'market_cap',
  'score',
] as const;

type PeerNumericField = (typeof PEER_NUMERIC_FIELDS)[number];

const VALUATION_NUMERIC_FIELDS = [
  'market_cap',
  'trailing_pe',
  'forward_pe',
  'price_to_book',
  'price_to_sales',
  'ev_to_ebitda',
  'dividend_yield',
  'beta',
  'week52_high',
  'week52_low',
] as const;

type ValuationNumericField = (typeof VALUATION_NUMERIC_FIELDS)[number];

const EARNINGS_NUMERIC_FIELDS = ['eps_estimate', 'eps_actual', 'surprise_pct'] as const;

type EarningsNumericField = (typeof EARNINGS_NUMERIC_FIELDS)[number];

/**
 * Parse raw `<chart ...>JSON</chart>` or `<chart_ref .../>` block strings
 * into structured SmartChartBlock objects.
 */
// eslint-disable-next-line react-refresh/only-export-components -- shared parser utility for ChatList
export function parseSmartChartBlocks(content: string): SmartChartBlock[] {
  const blocks: SmartChartBlock[] = [];

  // Match <chart type="..." title="...">JSON</chart>
  const inlineRegex = /<chart\s+([^>]*)>([\s\S]*?)<\/chart>/g;
  for (const match of content.matchAll(inlineRegex)) {
    const attrs = match[1];
    const json = match[2].trim();
    const type = extractAttr(attrs, 'type');
    const title = extractAttr(attrs, 'title') ?? '';
    if (!isSmartChartType(type)) continue;
    blocks.push({ mode: 'inline', type, title, dataJson: json });
  }

  // Match <chart_ref type="..." source="..." fields="..." title="..."/>
  const refRegex = /<chart_ref\s+([^>]*?)\/>/g;
  for (const match of content.matchAll(refRegex)) {
    const attrs = match[1];
    const type = extractAttr(attrs, 'type');
    const title = extractAttr(attrs, 'title') ?? '';
    const source = extractAttr(attrs, 'source') ?? '';
    const fields = extractAttr(attrs, 'fields') ?? '';
    if (!isSmartChartType(type)) continue;
    blocks.push({ mode: 'ref', type, title, source, fields });
  }

  // 每条消息最多渲染 4 张 SmartChart，避免聊天气泡过长。
  return blocks.slice(0, 4);
}

/**
 * Remove all <chart>...</chart> and <chart_ref .../> tags from content.
 */
// eslint-disable-next-line react-refresh/only-export-components -- shared parser utility for ChatList
export function stripSmartChartTags(content: string): string {
  return content
    .replace(/<chart\s+[^>]*>[\s\S]*?<\/chart>/g, '')
    .replace(/<chart_ref\s+[^>]*?\/>/g, '')
    .trim();
}

function extractAttr(attrs: string, name: string): string | undefined {
  const regex = new RegExp(`${name}=["']([^"']*)["']`);
  const match = attrs.match(regex);
  return match?.[1];
}

function isSmartChartType(value: string | undefined): value is SmartChartType {
  return typeof value === 'string' && (VALID_TYPES as readonly string[]).includes(value);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function toChartNumber(value: unknown): number {
  const numeric = typeof value === 'number'
    ? value
    : typeof value === 'string' || typeof value === 'boolean' || value === null
      ? Number(value)
      : NaN;
  return Number.isFinite(numeric) ? numeric : 0;
}

function toOptionalNumber(value: unknown): number | undefined {
  const numeric = typeof value === 'number'
    ? value
    : typeof value === 'string' && value.trim() !== ''
      ? Number(value)
      : NaN;
  return Number.isFinite(numeric) ? numeric : undefined;
}

function toStringArray(value: unknown): string[] | null {
  if (!Array.isArray(value)) return null;
  return value.map(String);
}

function toNumberArray(value: unknown): number[] | undefined {
  if (!Array.isArray(value)) return undefined;
  return value.map(toChartNumber);
}

function toOhlcArray(value: unknown): SmartChartOhlcPoint[] | undefined {
  if (!Array.isArray(value)) return undefined;

  const rows: SmartChartOhlcPoint[] = [];
  for (const row of value) {
    if (!Array.isArray(row) || row.length < 4) return undefined;
    rows.push([
      toChartNumber(row[0]),
      toChartNumber(row[1]),
      toChartNumber(row[2]),
      toChartNumber(row[3]),
    ]);
  }

  return rows.length > 0 ? rows : undefined;
}

function toSeriesArray(value: unknown): SmartChartSeries[] | undefined {
  if (!Array.isArray(value)) return undefined;

  const series = value.flatMap((entry, index): SmartChartSeries[] => {
    if (!isRecord(entry)) return [];
    const values = toNumberArray(entry.values);
    if (!values?.length) return [];

    const rawName = entry.name;
    const rawUnit = entry.unit;
    return [{
      name: typeof rawName === 'string' && rawName.trim() ? rawName : `Series ${index + 1}`,
      values,
      ...(typeof rawUnit === 'string' ? { unit: rawUnit } : {}),
    }];
  });

  return series.length > 0 ? series : undefined;
}

function toBandArray(value: unknown): SmartChartBand[] | undefined {
  if (!Array.isArray(value)) return undefined;

  const bands = value.flatMap((entry, index): SmartChartBand[] => {
    if (!isRecord(entry)) return [];
    const values = toNumberArray(entry.values);
    if (!values?.length) return [];

    const rawName = entry.name;
    return [{
      name: typeof rawName === 'string' && rawName.trim() ? rawName : `Band ${index + 1}`,
      values,
    }];
  });

  return bands.length > 0 ? bands : undefined;
}

function toEventArray(value: unknown): SmartChartEvent[] | undefined {
  if (!Array.isArray(value)) return undefined;

  const events = value.flatMap((entry): SmartChartEvent[] => {
    if (!isRecord(entry)) return [];

    const rawLabel = entry.label ?? entry.name ?? entry.title;
    if (rawLabel === undefined || rawLabel === null) return [];

    const rawDate = entry.date ?? entry.ts ?? entry.time;
    const rawKind = entry.kind ?? entry.type;
    const index = toOptionalNumber(entry.index);
    const eventValue = toOptionalNumber(entry.value);

    return [{
      label: String(rawLabel),
      ...(typeof rawDate === 'string' || typeof rawDate === 'number' ? { date: String(rawDate) } : {}),
      ...(index !== undefined ? { index } : {}),
      ...(eventValue !== undefined ? { value: eventValue } : {}),
      ...(typeof rawKind === 'string' ? { kind: rawKind } : {}),
    }];
  });

  return events.length > 0 ? events : undefined;
}

function parseInlineData(json: string): SmartChartData | null {
  try {
    const parsed: unknown = JSON.parse(json);
    if (!isRecord(parsed)) return null;

    const labels = toStringArray(parsed.labels);
    const ohlc = toOhlcArray(parsed.ohlc);
    const series = toSeriesArray(parsed.series);
    const parsedValues = toNumberArray(parsed.values);
    const values = parsedValues?.length ? parsedValues : ohlc?.map((row) => row[1]) ?? series?.[0]?.values;

    if (!labels?.length || !values?.length) return null;

    const unit = typeof parsed.unit === 'string' ? parsed.unit : undefined;
    const volume = toNumberArray(parsed.volume);
    const bands = toBandArray(parsed.bands);
    const events = toEventArray(parsed.events);

    return {
      labels,
      values,
      ...(unit ? { unit } : {}),
      ...(series ? { series } : {}),
      ...(ohlc ? { ohlc } : {}),
      ...(volume?.length ? { volume } : {}),
      ...(bands ? { bands } : {}),
      ...(events ? { events } : {}),
    };
  } catch {
    return null;
  }
}

// --- ECharts Option Builders ---

function buildBarOption(data: SmartChartData, title: string, theme: ChartTheme) {
  return {
    tooltip: {
      trigger: 'axis' as const,
      backgroundColor: theme.tooltipBackground,
      borderColor: theme.tooltipBorder,
      textStyle: { color: theme.tooltipText, fontSize: 11 },
    },
    grid: { left: 48, right: 16, top: 32, bottom: 24 },
    title: {
      text: title,
      left: 'center',
      textStyle: { color: theme.text, fontSize: 12, fontWeight: 500 },
    },
    xAxis: {
      type: 'category' as const,
      data: data.labels,
      axisLabel: { color: theme.muted, fontSize: 10, rotate: data.labels.length > 6 ? 30 : 0 },
      axisLine: { lineStyle: { color: theme.border } },
    },
    yAxis: {
      type: 'value' as const,
      axisLabel: {
        color: theme.muted,
        fontSize: 9,
        formatter: data.unit ? `{value}${data.unit}` : '{value}',
      },
      splitLine: { lineStyle: { color: theme.grid, type: 'dashed' } },
    },
    series: [{
      type: 'bar',
      data: data.values.map((v, i) => ({
        value: v,
        itemStyle: { color: i === 0 ? theme.primary : theme.primarySoft, borderRadius: [3, 3, 0, 0] },
      })),
      barMaxWidth: 40,
    }],
  };
}

function buildLineOption(data: SmartChartData, title: string, theme: ChartTheme) {
  return {
    tooltip: {
      trigger: 'axis' as const,
      backgroundColor: theme.tooltipBackground,
      borderColor: theme.tooltipBorder,
      textStyle: { color: theme.tooltipText, fontSize: 11 },
    },
    grid: { left: 48, right: 16, top: 32, bottom: 24 },
    title: {
      text: title,
      left: 'center',
      textStyle: { color: theme.text, fontSize: 12, fontWeight: 500 },
    },
    xAxis: {
      type: 'category' as const,
      data: data.labels,
      axisLabel: { color: theme.muted, fontSize: 10 },
      axisLine: { lineStyle: { color: theme.border } },
    },
    yAxis: {
      type: 'value' as const,
      axisLabel: { color: theme.muted, fontSize: 9 },
      splitLine: { lineStyle: { color: theme.grid, type: 'dashed' } },
    },
    series: [{
      type: 'line',
      data: data.values,
      smooth: true,
      showSymbol: true,
      symbolSize: 5,
      lineStyle: { color: theme.primary, width: 2 },
      itemStyle: { color: theme.primary },
      areaStyle: { opacity: 0.1 },
    }],
  };
}

function buildPieOption(data: SmartChartData, title: string, theme: ChartTheme) {
  const pieData = data.labels.map((label, i) => ({
    name: label,
    value: data.values[i],
  }));

  const colors = [theme.primary, theme.success, theme.warning, theme.danger, '#8b5cf6', '#06b6d4', '#ec4899'];

  return {
    tooltip: {
      trigger: 'item' as const,
      backgroundColor: theme.tooltipBackground,
      borderColor: theme.tooltipBorder,
      textStyle: { color: theme.tooltipText, fontSize: 11 },
    },
    title: {
      text: title,
      left: 'center',
      textStyle: { color: theme.text, fontSize: 12, fontWeight: 500 },
    },
    series: [{
      type: 'pie',
      radius: ['35%', '65%'],
      center: ['50%', '55%'],
      data: pieData,
      label: {
        color: theme.muted,
        fontSize: 10,
        formatter: '{b}: {d}%',
      },
      itemStyle: {
        borderColor: theme.isDark ? '#1e2028' : '#ffffff',
        borderWidth: 2,
      },
      color: colors,
    }],
  };
}

function buildScatterOption(data: SmartChartData, title: string, theme: ChartTheme) {
  // For scatter, values are treated as Y coords, labels as X
  const scatterData = data.labels.map((_, i) => [i, data.values[i]]);

  return {
    tooltip: {
      trigger: 'item' as const,
      backgroundColor: theme.tooltipBackground,
      borderColor: theme.tooltipBorder,
      textStyle: { color: theme.tooltipText, fontSize: 11 },
      formatter: (p: { dataIndex: number; value: [number, number] }) =>
        `${data.labels[p.dataIndex]}: ${p.value[1]}`,
    },
    grid: { left: 48, right: 16, top: 32, bottom: 24 },
    title: {
      text: title,
      left: 'center',
      textStyle: { color: theme.text, fontSize: 12, fontWeight: 500 },
    },
    xAxis: {
      type: 'category' as const,
      data: data.labels,
      axisLabel: { color: theme.muted, fontSize: 10 },
      axisLine: { lineStyle: { color: theme.border } },
    },
    yAxis: {
      type: 'value' as const,
      axisLabel: { color: theme.muted, fontSize: 9 },
      splitLine: { lineStyle: { color: theme.grid, type: 'dashed' } },
    },
    series: [{
      type: 'scatter',
      data: scatterData,
      symbolSize: 12,
      itemStyle: { color: theme.primary, opacity: 0.8 },
    }],
  };
}

function buildGaugeOption(data: SmartChartData, title: string, theme: ChartTheme) {
  const value = data.values[0] ?? 0;
  const label = data.labels[0] ?? '';

  return {
    title: {
      text: title,
      left: 'center',
      textStyle: { color: theme.text, fontSize: 12, fontWeight: 500 },
    },
    series: [{
      type: 'gauge',
      startAngle: 200,
      endAngle: -20,
      min: 0,
      max: 100,
      detail: {
        valueAnimation: true,
        formatter: `{value}${data.unit ?? ''}`,
        fontSize: 16,
        color: theme.text,
        offsetCenter: [0, '60%'],
      },
      data: [{ value, name: label }],
      axisLine: {
        lineStyle: {
          width: 12,
          color: [
            [0.3, theme.danger],
            [0.7, theme.warning],
            [1, theme.success],
          ],
        },
      },
      pointer: { itemStyle: { color: theme.primary } },
      axisTick: { show: false },
      splitLine: { show: false },
      axisLabel: { show: false },
      title: { show: true, offsetCenter: [0, '80%'], fontSize: 11, color: theme.muted },
    }],
  };
}

const FINANCIAL_CHART_COLORS = (theme: ChartTheme) => [
  theme.primary,
  theme.success,
  theme.warning,
  theme.danger,
  '#8b5cf6',
  '#06b6d4',
  '#ec4899',
];

function buildSmartChartTitle(title: string, theme: ChartTheme) {
  return {
    text: title,
    left: 'center',
    textStyle: { color: theme.text, fontSize: 12, fontWeight: 500 },
  };
}

function buildAxisTooltip(theme: ChartTheme, axisPointerType: 'line' | 'cross' | 'shadow' = 'line') {
  return {
    trigger: 'axis' as const,
    axisPointer: {
      type: axisPointerType,
      lineStyle: { color: theme.crosshair, width: 1, type: 'dashed' },
      crossStyle: { color: theme.crosshair, width: 1, type: 'dashed' },
    },
    backgroundColor: theme.tooltipBackground,
    borderColor: theme.tooltipBorder,
    textStyle: { color: theme.tooltipText, fontSize: 11 },
  };
}

function buildCategoryAxis(labels: string[], theme: ChartTheme, rotate = 0) {
  return {
    type: 'category' as const,
    data: labels,
    axisLabel: { color: theme.muted, fontSize: 10, rotate, hideOverlap: true },
    axisLine: { lineStyle: { color: theme.border } },
    axisTick: { alignWithLabel: true },
    splitLine: { show: false },
  };
}

function buildValueAxis(theme: ChartTheme, unit?: string, scale = false) {
  return {
    type: 'value' as const,
    scale,
    axisLabel: {
      color: theme.muted,
      fontSize: 9,
      formatter: unit ? `{value}${unit}` : '{value}',
    },
    splitLine: { lineStyle: { color: theme.grid, type: 'dashed' } },
  };
}

function buildDataZoom(theme: ChartTheme, xAxisIndex: number | number[] = 0) {
  return [
    { type: 'inside' as const, xAxisIndex, start: 60, end: 100 },
    {
      type: 'slider' as const,
      xAxisIndex,
      bottom: 6,
      height: 16,
      borderColor: theme.border,
      fillerColor: theme.sliderFiller,
      handleStyle: { color: theme.primary },
      textStyle: { color: theme.muted, fontSize: 9 },
    },
  ];
}

function alignValues(values: number[], length: number): number[] {
  return Array.from({ length }, (_, index) => values[index] ?? 0);
}

function firstNonZeroValue(values: number[]): number | null {
  const value = values.find((entry) => Number.isFinite(entry) && entry !== 0);
  return value === undefined ? null : value;
}

function normalizeToBase100(values: number[]): number[] | null {
  const base = firstNonZeroValue(values);
  if (base === null) return null;
  return values.map((value) => (value / base) * 100);
}

function calculateDrawdownValues(values: number[]): number[] {
  const alreadyDrawdown = values.every((value) => value <= 0);
  if (alreadyDrawdown) return values;

  let runningPeak = values[0] ?? 0;
  return values.map((value) => {
    runningPeak = Math.max(runningPeak, value);
    if (runningPeak === 0) return 0;
    return ((value - runningPeak) / runningPeak) * 100;
  });
}

function getBandRange(bands: SmartChartBand[], labelsLength: number): { lower: number[]; spread: number[] } | null {
  if (bands.length < 2) return null;

  const lower: number[] = [];
  const spread: number[] = [];
  for (let index = 0; index < labelsLength; index += 1) {
    const values = bands
      .map((band) => band.values[index])
      .filter((value): value is number => typeof value === 'number' && Number.isFinite(value));
    if (values.length < 2) return null;

    const min = Math.min(...values);
    const max = Math.max(...values);
    lower.push(min);
    spread.push(max - min);
  }

  return { lower, spread };
}

function buildEventMarkPoints(
  events: SmartChartEvent[] | undefined,
  labels: string[],
  fallbackValues: number[],
  theme: ChartTheme,
) {
  if (!events?.length) return undefined;

  const points = events.flatMap((event) => {
    const index = event.index !== undefined
      ? Math.trunc(event.index)
      : event.date
        ? labels.indexOf(event.date)
        : -1;
    if (index < 0 || index >= labels.length) return [];

    const value = event.value ?? fallbackValues[index] ?? 0;
    const color = event.kind === 'risk'
      ? theme.danger
      : event.kind === 'catalyst'
        ? theme.success
        : theme.warning;

    return [{
      name: event.label,
      coord: [labels[index], value],
      value: event.label,
      itemStyle: { color },
      label: { formatter: event.label, color: theme.text, fontSize: 9 },
    }];
  });

  return points.length > 0
    ? { symbolSize: 36, data: points }
    : undefined;
}

function buildCandlestickOption(data: SmartChartData, title: string, theme: ChartTheme) {
  if (!data.ohlc?.length || data.ohlc.length !== data.labels.length) return null;

  const closeValues = data.ohlc.map((row) => row[1]);
  const eventMarkPoints = buildEventMarkPoints(data.events, data.labels, closeValues, theme);

  return {
    tooltip: buildAxisTooltip(theme, 'cross'),
    grid: { left: 52, right: 16, top: 34, bottom: data.labels.length > 24 ? 36 : 26 },
    title: buildSmartChartTitle(title, theme),
    xAxis: buildCategoryAxis(data.labels, theme, data.labels.length > 8 ? 30 : 0),
    yAxis: buildValueAxis(theme, data.unit, true),
    dataZoom: data.labels.length > 24 ? buildDataZoom(theme) : undefined,
    series: [{
      name: title || 'K线',
      type: 'candlestick',
      data: data.ohlc,
      itemStyle: {
        color: theme.success,
        color0: theme.danger,
        borderColor: theme.success,
        borderColor0: theme.danger,
      },
      ...(eventMarkPoints ? { markPoint: eventMarkPoints } : {}),
    }],
  };
}

function buildPriceVolumeOption(data: SmartChartData, title: string, theme: ChartTheme) {
  if (!data.volume?.length || data.volume.length !== data.labels.length) return null;

  const hasOhlc = data.ohlc?.length === data.labels.length;
  const priceValues = hasOhlc ? data.ohlc?.map((row) => row[1]) ?? [] : alignValues(data.values, data.labels.length);
  if (priceValues.length !== data.labels.length) return null;

  const eventMarkPoints = buildEventMarkPoints(data.events, data.labels, priceValues, theme);
  const priceSeries = hasOhlc
    ? {
      name: '价格',
      type: 'candlestick',
      data: data.ohlc,
      xAxisIndex: 0,
      yAxisIndex: 0,
      itemStyle: {
        color: theme.success,
        color0: theme.danger,
        borderColor: theme.success,
        borderColor0: theme.danger,
      },
      ...(eventMarkPoints ? { markPoint: eventMarkPoints } : {}),
    }
    : {
      name: '价格',
      type: 'line',
      data: priceValues,
      xAxisIndex: 0,
      yAxisIndex: 0,
      smooth: true,
      showSymbol: false,
      lineStyle: { color: theme.primary, width: 2 },
      itemStyle: { color: theme.primary },
      areaStyle: { color: theme.primaryFaint },
      ...(eventMarkPoints ? { markPoint: eventMarkPoints } : {}),
    };

  return {
    tooltip: buildAxisTooltip(theme, 'cross'),
    title: buildSmartChartTitle(title, theme),
    grid: [
      { left: 52, right: 18, top: 34, height: '54%' },
      { left: 52, right: 18, top: '74%', bottom: 22 },
    ],
    xAxis: [
      {
        ...buildCategoryAxis(data.labels, theme, 0),
        boundaryGap: false,
        gridIndex: 0,
        axisLabel: { show: false },
      },
      {
        ...buildCategoryAxis(data.labels, theme, data.labels.length > 8 ? 30 : 0),
        gridIndex: 1,
      },
    ],
    yAxis: [
      { ...buildValueAxis(theme, data.unit, true), gridIndex: 0 },
      {
        ...buildValueAxis(theme, undefined, true),
        gridIndex: 1,
        axisLabel: { color: theme.muted, fontSize: 9 },
        splitLine: { show: false },
      },
    ],
    dataZoom: data.labels.length > 24 ? buildDataZoom(theme, [0, 1]) : undefined,
    series: [
      priceSeries,
      {
        name: '成交量',
        type: 'bar',
        data: data.volume,
        xAxisIndex: 1,
        yAxisIndex: 1,
        itemStyle: { color: theme.primarySoft },
        barMaxWidth: 12,
      },
    ],
  };
}

function buildRsLineOption(data: SmartChartData, title: string, theme: ChartTheme) {
  if (!data.series || data.series.length < 2) return null;

  const colors = FINANCIAL_CHART_COLORS(theme);
  const normalizedSeries = data.series.flatMap((series, index) => {
    const normalized = normalizeToBase100(alignValues(series.values, data.labels.length));
    if (!normalized) return [];

    return [{
      name: series.name,
      type: 'line',
      data: normalized,
      smooth: true,
      showSymbol: false,
      lineStyle: { color: colors[index % colors.length], width: index === 0 ? 2.4 : 1.8 },
      itemStyle: { color: colors[index % colors.length] },
    }];
  });

  if (normalizedSeries.length < 2) return null;

  return {
    tooltip: buildAxisTooltip(theme),
    legend: {
      top: 16,
      left: 'center',
      textStyle: { color: theme.muted, fontSize: 10 },
      itemWidth: 10,
      itemHeight: 6,
    },
    grid: { left: 48, right: 16, top: 48, bottom: 24 },
    title: buildSmartChartTitle(title, theme),
    xAxis: buildCategoryAxis(data.labels, theme, data.labels.length > 8 ? 30 : 0),
    yAxis: {
      ...buildValueAxis(theme, undefined, false),
      axisLabel: { color: theme.muted, fontSize: 9, formatter: '{value}' },
    },
    series: normalizedSeries,
  };
}

function buildWaterfallOption(data: SmartChartData, title: string, theme: ChartTheme) {
  if (!data.labels.length || !data.values.length) return null;

  let cumulative = 0;
  const helper: number[] = [];
  const deltas = alignValues(data.values, data.labels.length);
  const bars = deltas.map((delta) => {
    const start = cumulative;
    cumulative += delta;
    helper.push(delta >= 0 ? start : cumulative);
    return Math.abs(delta);
  });

  return {
    tooltip: {
      ...buildAxisTooltip(theme, 'shadow'),
      formatter: (params: Array<{ seriesName: string; axisValue: string; value: number }>) => {
        const row = params.find((item) => item.seriesName === '变动');
        const index = data.labels.indexOf(row?.axisValue ?? '');
        const value = deltas[index] ?? 0;
        const sign = value >= 0 ? '+' : '';
        return `<b>${row?.axisValue ?? ''}</b><br/>变动: ${sign}${value.toFixed(2)}${data.unit ?? ''}`;
      },
    },
    grid: { left: 50, right: 16, top: 34, bottom: 28 },
    title: buildSmartChartTitle(title, theme),
    xAxis: buildCategoryAxis(data.labels, theme, data.labels.length > 8 ? 30 : 0),
    yAxis: buildValueAxis(theme, data.unit),
    series: [
      {
        name: '占位',
        type: 'bar',
        stack: 'waterfall',
        silent: true,
        itemStyle: { color: 'rgba(0,0,0,0)', borderColor: 'rgba(0,0,0,0)' },
        emphasis: { itemStyle: { color: 'rgba(0,0,0,0)' } },
        data: helper,
      },
      {
        name: '变动',
        type: 'bar',
        stack: 'waterfall',
        data: bars.map((value, index) => ({
          value,
          itemStyle: {
            color: deltas[index] >= 0 ? theme.success : theme.danger,
            borderRadius: deltas[index] >= 0 ? [3, 3, 0, 0] : [0, 0, 3, 3],
          },
        })),
        barMaxWidth: 36,
        label: {
          show: true,
          position: 'top',
          color: theme.muted,
          fontSize: 9,
          formatter: (params: { dataIndex: number }) => {
            const value = deltas[params.dataIndex] ?? 0;
            if (Math.abs(value) < 0.01) return '';
            return `${value >= 0 ? '+' : ''}${value.toFixed(1)}`;
          },
        },
      },
    ],
  };
}

function buildHeatmapOption(data: SmartChartData, title: string, theme: ChartTheme) {
  if (!data.series?.length) return null;

  const matrix = data.series.flatMap((series, rowIndex) =>
    alignValues(series.values, data.labels.length).map((value, columnIndex) => [columnIndex, rowIndex, value])
  );
  if (!matrix.length) return null;

  const values = matrix.map((entry) => entry[2]);
  const min = Math.min(...values);
  const max = Math.max(...values);

  return {
    tooltip: {
      trigger: 'item' as const,
      backgroundColor: theme.tooltipBackground,
      borderColor: theme.tooltipBorder,
      textStyle: { color: theme.tooltipText, fontSize: 11 },
      formatter: (params: { value: [number, number, number] }) => {
        const [columnIndex, rowIndex, value] = params.value;
        return `<b>${data.series?.[rowIndex]?.name ?? ''}</b><br/>${data.labels[columnIndex] ?? ''}: ${value.toFixed(2)}${data.unit ?? ''}`;
      },
    },
    title: buildSmartChartTitle(title, theme),
    grid: { left: 64, right: 18, top: 34, bottom: 42 },
    xAxis: buildCategoryAxis(data.labels, theme, data.labels.length > 8 ? 30 : 0),
    yAxis: {
      type: 'category' as const,
      data: data.series.map((series) => series.name),
      axisLabel: { color: theme.muted, fontSize: 10 },
      axisLine: { lineStyle: { color: theme.border } },
      axisTick: { show: false },
      splitLine: { show: false },
    },
    visualMap: {
      min,
      max,
      calculable: true,
      orient: 'horizontal' as const,
      left: 'center',
      bottom: 0,
      itemHeight: 70,
      itemWidth: 8,
      textStyle: { color: theme.muted, fontSize: 9 },
      inRange: { color: [theme.danger, theme.warning, theme.success] },
    },
    series: [{
      name: title || '热力',
      type: 'heatmap',
      data: matrix,
      label: {
        show: data.labels.length <= 8 && data.series.length <= 5,
        color: theme.text,
        fontSize: 9,
      },
      emphasis: {
        itemStyle: { shadowBlur: 8, shadowColor: theme.primarySoft },
      },
    }],
  };
}

function buildRadarOption(data: SmartChartData, title: string, theme: ChartTheme) {
  if (data.labels.length < 3 || data.values.length < 3) return null;

  const radarSeries = data.series?.length
    ? data.series
    : [{ name: title || '指标', values: data.values }];
  const alignedSeries = radarSeries.map((series) => ({
    name: series.name,
    values: alignValues(series.values, data.labels.length),
  }));
  const indicators = data.labels.map((label, index) => {
    const maxValue = Math.max(
      ...alignedSeries.map((series) => Math.abs(series.values[index] ?? 0)),
      Math.abs(data.values[index] ?? 0),
      1,
    );
    return { name: label, max: maxValue * 1.2 };
  });
  const colors = FINANCIAL_CHART_COLORS(theme);

  return {
    tooltip: {
      trigger: 'item' as const,
      backgroundColor: theme.tooltipBackground,
      borderColor: theme.tooltipBorder,
      textStyle: { color: theme.tooltipText, fontSize: 11 },
    },
    title: buildSmartChartTitle(title, theme),
    legend: data.series?.length
      ? {
        bottom: 0,
        textStyle: { color: theme.muted, fontSize: 10 },
        itemWidth: 10,
        itemHeight: 6,
      }
      : undefined,
    radar: {
      center: ['50%', '55%'],
      radius: '62%',
      indicator: indicators,
      axisName: { color: theme.muted, fontSize: 10 },
      axisLine: { lineStyle: { color: theme.border } },
      splitLine: { lineStyle: { color: theme.grid } },
      splitArea: {
        areaStyle: { color: [theme.splitAreaA, theme.splitAreaB] },
      },
    },
    series: [{
      type: 'radar',
      data: alignedSeries.map((series, index) => ({
        name: series.name,
        value: series.values,
        areaStyle: { color: index === 0 ? theme.primaryFaint : undefined },
        lineStyle: { color: colors[index % colors.length], width: 2 },
        itemStyle: { color: colors[index % colors.length] },
      })),
    }],
  };
}

function buildValuationBandOption(data: SmartChartData, title: string, theme: ChartTheme) {
  if (!data.bands?.length) return null;

  const bands = data.bands;
  const range = getBandRange(bands, data.labels.length);
  if (!range) return null;

  const currentValues = alignValues(data.values, data.labels.length);
  const currentValue = currentValues[currentValues.length - 1];
  const colors = FINANCIAL_CHART_COLORS(theme);

  return {
    tooltip: buildAxisTooltip(theme),
    title: buildSmartChartTitle(title, theme),
    grid: { left: 52, right: 18, top: 36, bottom: 28 },
    xAxis: buildCategoryAxis(data.labels, theme, data.labels.length > 8 ? 30 : 0),
    yAxis: buildValueAxis(theme, data.unit, true),
    series: [
      {
        name: '估值区间下沿',
        type: 'line',
        stack: 'valuation-band',
        data: range.lower,
        symbol: 'none',
        lineStyle: { opacity: 0 },
        areaStyle: { opacity: 0 },
        tooltip: { show: false },
      },
      {
        name: '估值区间',
        type: 'line',
        stack: 'valuation-band',
        data: range.spread,
        symbol: 'none',
        lineStyle: { opacity: 0 },
        areaStyle: { color: theme.primaryFaint },
        tooltip: { show: false },
      },
      ...bands.map((band, index) => ({
        name: band.name,
        type: 'line',
        data: alignValues(band.values, data.labels.length),
        smooth: true,
        showSymbol: false,
        lineStyle: {
          color: colors[(index + 1) % colors.length],
          width: index === Math.floor(bands.length / 2) ? 2 : 1.2,
          opacity: 0.75,
        },
        itemStyle: { color: colors[(index + 1) % colors.length] },
      })),
      {
        name: '当前值',
        type: 'line',
        data: currentValues,
        smooth: true,
        showSymbol: true,
        symbolSize: 5,
        lineStyle: { color: theme.primary, width: 2.4 },
        itemStyle: { color: theme.primary },
        markLine: currentValue === undefined
          ? undefined
          : {
            symbol: 'none',
            silent: true,
            lineStyle: { color: theme.warning, type: 'dashed', width: 1.5 },
            label: {
              formatter: `当前 ${currentValue.toFixed(2)}${data.unit ?? ''}`,
              color: theme.warning,
              fontSize: 10,
            },
            data: [{ yAxis: currentValue }],
          },
      },
    ],
  };
}

function buildBubbleOption(data: SmartChartData, title: string, theme: ChartTheme) {
  if (!data.series || data.series.length < 2) return null;

  const xValues = data.series.length >= 3
    ? alignValues(data.series[0].values, data.labels.length)
    : alignValues(data.values, data.labels.length);
  const ySeries = data.series.length >= 3 ? data.series[1] : data.series[0];
  const sizeSeries = data.series.length >= 3 ? data.series[2] : data.series[1];
  if (!ySeries || !sizeSeries) return null;

  const yValues = alignValues(ySeries.values, data.labels.length);
  const sizeValues = alignValues(sizeSeries.values, data.labels.length);
  const maxSize = Math.max(...sizeValues.map(Math.abs), 1);
  const bubbleData = data.labels.map((label, index) => [
    xValues[index] ?? 0,
    yValues[index] ?? 0,
    sizeValues[index] ?? 0,
    label,
  ]);

  return {
    tooltip: {
      trigger: 'item' as const,
      backgroundColor: theme.tooltipBackground,
      borderColor: theme.tooltipBorder,
      textStyle: { color: theme.tooltipText, fontSize: 11 },
      formatter: (params: { value: [number, number, number, string] }) => {
        const [xValue, yValue, sizeValue, label] = params.value;
        const xName = data.series && data.series.length >= 3 ? data.series[0]?.name : 'X';
        return `<b>${label}</b><br/>${xName}: ${xValue.toFixed(2)}<br/>${ySeries.name}: ${yValue.toFixed(2)}<br/>${sizeSeries.name}: ${sizeValue.toFixed(2)}`;
      },
    },
    title: buildSmartChartTitle(title, theme),
    grid: { left: 50, right: 18, top: 34, bottom: 28 },
    xAxis: {
      ...buildValueAxis(theme),
      name: data.series.length >= 3 ? data.series[0]?.name : '',
      nameTextStyle: { color: theme.muted, fontSize: 10 },
    },
    yAxis: {
      ...buildValueAxis(theme),
      name: ySeries.name,
      nameTextStyle: { color: theme.muted, fontSize: 10 },
    },
    series: [{
      name: title || '气泡',
      type: 'scatter',
      data: bubbleData,
      symbolSize: (value: [number, number, number]) => 8 + (Math.abs(value[2]) / maxSize) * 28,
      itemStyle: {
        color: theme.primary,
        opacity: 0.72,
        borderColor: theme.tooltipBackground,
        borderWidth: 1,
      },
      label: {
        show: data.labels.length <= 10,
        formatter: (params: { value: [number, number, number, string] }) => params.value[3],
        color: theme.muted,
        fontSize: 9,
        position: 'top',
      },
    }],
  };
}

function buildDrawdownOption(data: SmartChartData, title: string, theme: ChartTheme) {
  if (data.values.length < 2) return null;

  const drawdowns = calculateDrawdownValues(alignValues(data.values, data.labels.length));
  const minDrawdown = Math.min(...drawdowns);

  return {
    tooltip: {
      ...buildAxisTooltip(theme),
      formatter: (params: Array<{ axisValue: string; value: number }>) => {
        const point = params[0];
        if (!point) return '';
        return `<b>${point.axisValue}</b><br/>回撤: ${point.value.toFixed(2)}%`;
      },
    },
    grid: { left: 48, right: 16, top: 34, bottom: 26 },
    title: buildSmartChartTitle(title, theme),
    xAxis: buildCategoryAxis(data.labels, theme, data.labels.length > 8 ? 30 : 0),
    yAxis: {
      ...buildValueAxis(theme, '%'),
      max: 0,
      min: Math.min(minDrawdown * 1.15, -1),
    },
    series: [{
      name: '回撤',
      type: 'line',
      data: drawdowns,
      smooth: true,
      showSymbol: false,
      lineStyle: { color: theme.danger, width: 2 },
      itemStyle: { color: theme.danger },
      areaStyle: {
        color: {
          type: 'linear',
          x: 0,
          y: 0,
          x2: 0,
          y2: 1,
          colorStops: [
            { offset: 0, color: theme.primaryFaint },
            { offset: 1, color: theme.danger },
          ],
        },
        opacity: 0.22,
      },
      markLine: {
        symbol: 'none',
        silent: true,
        lineStyle: { color: theme.border, type: 'dashed' },
        label: { show: false },
        data: [{ yAxis: 0 }],
      },
    }],
  };
}

function buildScenarioOption(data: SmartChartData, title: string, theme: ChartTheme) {
  if (!data.series?.length || !data.bands?.length) return null;

  const range = getBandRange(data.bands, data.labels.length);
  if (!range) return null;

  const colors = FINANCIAL_CHART_COLORS(theme);
  const eventMarkPoints = buildEventMarkPoints(data.events, data.labels, data.series[0]?.values ?? [], theme);

  return {
    tooltip: buildAxisTooltip(theme),
    legend: {
      top: 16,
      left: 'center',
      textStyle: { color: theme.muted, fontSize: 10 },
      itemWidth: 10,
      itemHeight: 6,
    },
    title: buildSmartChartTitle(title, theme),
    grid: { left: 52, right: 18, top: 50, bottom: 28 },
    xAxis: buildCategoryAxis(data.labels, theme, data.labels.length > 8 ? 30 : 0),
    yAxis: buildValueAxis(theme, data.unit, true),
    series: [
      {
        name: '情景区间下沿',
        type: 'line',
        stack: 'scenario-band',
        data: range.lower,
        symbol: 'none',
        lineStyle: { opacity: 0 },
        areaStyle: { opacity: 0 },
        tooltip: { show: false },
      },
      {
        name: '情景区间',
        type: 'line',
        stack: 'scenario-band',
        data: range.spread,
        symbol: 'none',
        lineStyle: { opacity: 0 },
        areaStyle: { color: theme.primaryFaint },
        tooltip: { show: false },
      },
      ...data.series.map((series, index) => ({
        name: series.name,
        type: 'line',
        data: alignValues(series.values, data.labels.length),
        smooth: true,
        showSymbol: index === 0,
        symbolSize: 5,
        lineStyle: { color: colors[index % colors.length], width: index === 0 ? 2.4 : 1.8 },
        itemStyle: { color: colors[index % colors.length] },
        ...(index === 0 && eventMarkPoints ? { markPoint: eventMarkPoints } : {}),
      })),
    ],
  };
}

// --- Chart Ref Data Resolver ---

function splitFields(fields: string, fallback: string[]): string[] {
  const parsed = fields.split(',').map((field) => field.trim()).filter(Boolean);
  return parsed.length > 0 ? parsed : fallback;
}

function formatFieldLabel(field: string): string {
  return field.replace(/_/g, ' ');
}

function isFiniteNumber(value: number | null | undefined): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function isFinancialNumericField(field: string): field is FinancialNumericField {
  return (FINANCIAL_NUMERIC_FIELDS as readonly string[]).includes(field);
}

function isTechnicalNumericField(field: string): field is TechnicalNumericField {
  return (TECHNICAL_NUMERIC_FIELDS as readonly string[]).includes(field);
}

function isPeerNumericField(field: string): field is PeerNumericField {
  return (PEER_NUMERIC_FIELDS as readonly string[]).includes(field);
}

function isValuationNumericField(field: string): field is ValuationNumericField {
  return (VALUATION_NUMERIC_FIELDS as readonly string[]).includes(field);
}

function isEarningsNumericField(field: string): field is EarningsNumericField {
  return (EARNINGS_NUMERIC_FIELDS as readonly string[]).includes(field);
}

function readChartPointNumber(point: ChartPoint, field: string): number | null {
  switch (field) {
    case 'open': return isFiniteNumber(point.open) ? point.open : null;
    case 'high': return isFiniteNumber(point.high) ? point.high : null;
    case 'low': return isFiniteNumber(point.low) ? point.low : null;
    case 'close':
    case 'price': return isFiniteNumber(point.close) ? point.close : null;
    case 'value': return isFiniteNumber(point.value) ? point.value : null;
    case 'volume': return isFiniteNumber(point.volume) ? point.volume : null;
    case 'weight': return isFiniteNumber(point.weight) ? point.weight : null;
    default: return null;
  }
}

function formatChartPointLabel(point: ChartPoint, index: number): string {
  if (point.period) return point.period;
  if (point.name) return point.name;
  if (isFiniteNumber(point.time)) {
    return new Date(point.time).toLocaleDateString();
  }
  if (point.symbol) return point.symbol;
  return String(index + 1);
}

function buildMarketChartData(points: ChartPoint[], fields: string): SmartChartData | null {
  if (points.length === 0) return null;

  const valueField = splitFields(fields, ['close'])[0] ?? 'close';
  const labels = points.map(formatChartPointLabel);
  const values = points.map((point) =>
    readChartPointNumber(point, valueField)
    ?? readChartPointNumber(point, 'close')
    ?? readChartPointNumber(point, 'value')
    ?? 0
  );

  const ohlcRows = points.map((point): SmartChartOhlcPoint | null => {
    const open = readChartPointNumber(point, 'open');
    const close = readChartPointNumber(point, 'close');
    const low = readChartPointNumber(point, 'low');
    const high = readChartPointNumber(point, 'high');
    return open !== null && close !== null && low !== null && high !== null
      ? [open, close, low, high]
      : null;
  });
  const volumeValues = points.map((point) => readChartPointNumber(point, 'volume'));
  const data: SmartChartData = { labels, values };

  if (ohlcRows.every((row): row is SmartChartOhlcPoint => row !== null)) {
    data.ohlc = ohlcRows;
  }
  if (volumeValues.some((value) => value !== null)) {
    data.volume = volumeValues.map((value) => value ?? 0);
  }

  return data;
}

function readFinancialSeries(financials: FinancialStatement, field: string): number[] | null {
  if (!isFinancialNumericField(field)) return null;
  return financials[field].map((value) => (isFiniteNumber(value) ? value : 0));
}

function buildFinancialsData(financials: FinancialStatement, fields: string): SmartChartData | null {
  if (financials.periods.length === 0) return null;

  const series = splitFields(fields, ['revenue']).flatMap((field): SmartChartSeries[] => {
    const values = readFinancialSeries(financials, field);
    return values ? [{ name: formatFieldLabel(field), values }] : [];
  });
  const firstSeries = series[0];
  if (!firstSeries) return null;

  return {
    labels: financials.periods,
    values: firstSeries.values,
    ...(series.length > 1 ? { series } : {}),
  };
}

function readTechnicalValue(technicals: TechnicalData, field: string): number | null {
  if (!isTechnicalNumericField(field)) return null;
  const value = technicals[field];
  return isFiniteNumber(value) ? value : null;
}

function buildTechnicalsData(technicals: TechnicalData, fields: string): SmartChartData | null {
  const rows = splitFields(fields, ['rsi', 'macd', 'macd_signal', 'adx']).flatMap((field) => {
    const value = readTechnicalValue(technicals, field);
    return value === null ? [] : [{ label: formatFieldLabel(field), value }];
  });

  if (rows.length === 0) return null;
  return {
    labels: rows.map((row) => row.label),
    values: rows.map((row) => row.value),
  };
}

function readPeerMetric(peer: PeerMetrics, field: string): number | null {
  if (!isPeerNumericField(field)) return null;
  const value = peer[field];
  return isFiniteNumber(value) ? value : null;
}

function buildPeersData(peers: PeerMetrics[], fields: string): SmartChartData | null {
  if (peers.length === 0) return null;

  const field = splitFields(fields, ['trailing_pe'])[0] ?? 'trailing_pe';
  return {
    labels: peers.map((peer) => peer.symbol || peer.name),
    values: peers.map((peer) => readPeerMetric(peer, field) ?? 0),
  };
}

function readValuationValue(valuation: ValuationData, field: string): number | null {
  if (!isValuationNumericField(field)) return null;
  const value = valuation[field];
  return isFiniteNumber(value) ? value : null;
}

function buildValuationData(valuation: ValuationData, fields: string): SmartChartData | null {
  const fieldList = splitFields(fields, []);
  if (fieldList.length === 0) return null;

  return {
    labels: fieldList.map(formatFieldLabel),
    values: fieldList.map((field) => readValuationValue(valuation, field) ?? 0),
  };
}

function buildNewsData(news: DashboardData['news'], fields: string): SmartChartData | null {
  const rows = splitFields(fields, ['market', 'impact']).flatMap((field) => {
    const value = news[field];
    return Array.isArray(value) ? [{ label: formatFieldLabel(field), value: value.length }] : [];
  });

  if (rows.length === 0) return null;
  return {
    labels: rows.map((row) => row.label),
    values: rows.map((row) => row.value),
  };
}

function readEarningsSeries(history: EarningsHistoryEntry[], field: string): number[] | null {
  if (!isEarningsNumericField(field)) return null;
  return history.map((entry) => {
    const value = entry[field];
    return isFiniteNumber(value) ? value : 0;
  });
}

function buildEarningsData(history: EarningsHistoryEntry[], fields: string): SmartChartData | null {
  if (history.length === 0) return null;

  const series = splitFields(fields, ['eps_actual']).flatMap((field): SmartChartSeries[] => {
    const values = readEarningsSeries(history, field);
    return values ? [{ name: formatFieldLabel(field), values }] : [];
  });
  const firstSeries = series[0];
  if (!firstSeries) return null;

  return {
    labels: history.map((entry) => entry.quarter),
    values: firstSeries.values,
    ...(series.length > 1 ? { series } : {}),
  };
}

function resolveRefData(
  source: string,
  fields: string,
  dashboardData: DashboardData | null,
): SmartChartData | null {
  if (!dashboardData) return null;

  try {
    if (source === 'peers') {
      return dashboardData.peers?.peers ? buildPeersData(dashboardData.peers.peers, fields) : null;
    }

    if (source === 'financials') {
      return dashboardData.financials ? buildFinancialsData(dashboardData.financials, fields) : null;
    }

    if (source === 'valuation') {
      return dashboardData.valuation ? buildValuationData(dashboardData.valuation, fields) : null;
    }

    if (source === 'market_chart') {
      const marketChart = dashboardData.charts.market_chart;
      return Array.isArray(marketChart) ? buildMarketChartData(marketChart, fields) : null;
    }

    if (source === 'technicals') {
      return dashboardData.technicals ? buildTechnicalsData(dashboardData.technicals, fields) : null;
    }

    if (source === 'news') {
      return dashboardData.news ? buildNewsData(dashboardData.news, fields) : null;
    }

    if (source === 'earnings') {
      return dashboardData.earnings_history
        ? buildEarningsData(dashboardData.earnings_history, fields)
        : null;
    }
  } catch {
    return null;
  }

  return null;
}

// --- Option Builder Router ---

function buildOption(
  type: SmartChartType,
  data: SmartChartData,
  title: string,
  theme: ChartTheme,
): Record<string, unknown> | null {
  switch (type) {
    case 'bar': return buildBarOption(data, title, theme);
    case 'line': return buildLineOption(data, title, theme);
    case 'pie': return buildPieOption(data, title, theme);
    case 'scatter': return buildScatterOption(data, title, theme);
    case 'gauge': return buildGaugeOption(data, title, theme);
    case 'candlestick': return buildCandlestickOption(data, title, theme);
    case 'price_volume': return buildPriceVolumeOption(data, title, theme);
    case 'rs_line': return buildRsLineOption(data, title, theme);
    case 'waterfall': return buildWaterfallOption(data, title, theme);
    case 'heatmap': return buildHeatmapOption(data, title, theme);
    case 'radar': return buildRadarOption(data, title, theme);
    case 'valuation_band': return buildValuationBandOption(data, title, theme);
    case 'bubble': return buildBubbleOption(data, title, theme);
    case 'drawdown': return buildDrawdownOption(data, title, theme);
    case 'scenario': return buildScenarioOption(data, title, theme);
    default: return null;
  }
}

// --- Component ---

interface SmartChartRendererProps {
  block: SmartChartBlock;
}

export function SmartChartRenderer({ block }: SmartChartRendererProps) {
  const theme = useChartTheme();
  const dashboardData = useDashboardStore((s) => s.dashboardData);

  const option = useMemo(() => {
    let data: SmartChartData | null = null;

    if (block.mode === 'inline' && block.dataJson) {
      data = parseInlineData(block.dataJson);
    } else if (block.mode === 'ref') {
      data = resolveRefData(
        block.source ?? '',
        block.fields ?? '',
        dashboardData,
      );
    }

    if (!data) return null;
    return buildOption(block.type, data, block.title, theme);
  }, [block, dashboardData, theme]);

  if (!option) return null;

  const height = block.type === 'gauge' ? 200 : block.type === 'pie' ? 220 : 200;

  return (
    <div className="my-3 p-3 bg-fin-card rounded-xl border border-fin-border">
      <ReactECharts
        option={option}
        style={{ width: '100%', height }}
        opts={{ renderer: 'svg' }}
        notMerge
        lazyUpdate
      />
    </div>
  );
}

export default SmartChartRenderer;
