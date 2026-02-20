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

// --- Types ---

export type SmartChartType = 'bar' | 'line' | 'pie' | 'scatter' | 'gauge';

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

interface SmartChartData {
  labels: string[];
  values: number[];
  unit?: string;
}

// --- Helpers ---

const VALID_TYPES: SmartChartType[] = ['bar', 'line', 'pie', 'scatter', 'gauge'];

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
    const type = extractAttr(attrs, 'type') as SmartChartType;
    const title = extractAttr(attrs, 'title') ?? '';
    if (!VALID_TYPES.includes(type)) continue;
    blocks.push({ mode: 'inline', type, title, dataJson: json });
  }

  // Match <chart_ref type="..." source="..." fields="..." title="..."/>
  const refRegex = /<chart_ref\s+([^>]*?)\/>/g;
  for (const match of content.matchAll(refRegex)) {
    const attrs = match[1];
    const type = extractAttr(attrs, 'type') as SmartChartType;
    const title = extractAttr(attrs, 'title') ?? '';
    const source = extractAttr(attrs, 'source') ?? '';
    const fields = extractAttr(attrs, 'fields') ?? '';
    if (!VALID_TYPES.includes(type)) continue;
    blocks.push({ mode: 'ref', type, title, source, fields });
  }

  // Limit to 2 charts per message
  return blocks.slice(0, 2);
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

function parseInlineData(json: string): SmartChartData | null {
  try {
    const parsed = JSON.parse(json);
    if (!Array.isArray(parsed.labels) || !Array.isArray(parsed.values)) return null;
    if (parsed.labels.length === 0 || parsed.values.length === 0) return null;
    return {
      labels: parsed.labels.map(String),
      values: parsed.values.map(Number),
      unit: parsed.unit ?? undefined,
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

// --- Chart Ref Data Resolver ---

function resolveRefData(
  source: string,
  fields: string,
  dashboardData: Record<string, unknown> | null,
): SmartChartData | null {
  if (!dashboardData) return null;

  try {
    if (source === 'peers') {
      const peers = dashboardData.peers as { peers?: Array<{ symbol: string; name: string; [k: string]: unknown }> } | null;
      if (!peers?.peers?.length) return null;
      const field = fields || 'trailing_pe';
      const labels = peers.peers.map((p) => p.symbol || p.name);
      const values = peers.peers.map((p) => {
        const v = p[field];
        return typeof v === 'number' ? v : 0;
      });
      return { labels, values };
    }

    if (source === 'financials') {
      const fin = dashboardData.financials as { periods?: string[]; [k: string]: unknown } | null;
      if (!fin?.periods?.length) return null;
      const field = fields || 'revenue';
      const labels = fin.periods;
      const rawValues = fin[field];
      if (!Array.isArray(rawValues)) return null;
      const values = rawValues.map((v: unknown) => (typeof v === 'number' ? v : 0));
      return { labels, values };
    }

    if (source === 'valuation') {
      const val = dashboardData.valuation as Record<string, unknown> | null;
      if (!val) return null;
      const fieldList = fields.split(',').map((f) => f.trim()).filter(Boolean);
      if (fieldList.length === 0) return null;
      const labels = fieldList.map((f) => f.replace(/_/g, ' '));
      const values = fieldList.map((f) => {
        const v = val[f];
        return typeof v === 'number' ? v : 0;
      });
      return { labels, values };
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
        dashboardData as unknown as Record<string, unknown>,
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
