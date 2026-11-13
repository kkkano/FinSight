import type { EChartsOption } from 'echarts';
import type { ResearchArtifact } from '../../types/runtime';
import { sourceDisplayName, sourceTitleDisplayName } from '../../utils/sourceDisplayName';

type ArtifactAnnotation = NonNullable<NonNullable<ResearchArtifact['spec']>['annotations']>[number];

export function artifactTheme(dark: boolean, convention: 'intl' | 'cn') {
  const green = dark ? '#4cc38a' : '#0f7a44';
  const red = dark ? '#ff7a7a' : '#c92a2a';
  const root = typeof document === 'undefined' ? undefined : getComputedStyle(document.documentElement);
  const color = (property: string, fallback: string) => root?.getPropertyValue(property).trim() || fallback;
  const accent = color('--t-accent', dark ? '128 152 255' : '59 91 219');
  return {
    up: color('--t-up', convention === 'cn' ? red : green),
    down: color('--t-down', convention === 'cn' ? green : red),
    palette: [`rgb(${accent.split(' ').join(',')})`, color('--t-teal', dark ? '#4cc9d8' : '#0b6e7f'),
      color('--t-amber', dark ? '#f2a74b' : '#a85400'), color('--t-violet', dark ? '#ad91ff' : '#6741d9')],
    text: color('--t-text-2', dark ? '#bcc2cd' : '#3f4b5e'),
    muted: color('--t-text-3', dark ? '#939bab' : '#5c6879'),
    border: color('--t-border', dark ? '#2b313b' : '#e2e5ea'),
    grid: color('--t-chart-grid', dark ? '#232831' : '#e8eaef'),
    downSoft: color('--t-down-soft', 'transparent'),
    background: color('--t-bg', dark ? '#0e1014' : '#ffffff'),
  };
}

function boundaryIndex(labels: string[], value: string | number, end: boolean): number {
  if (typeof value === 'number') return Math.max(0, Math.min(labels.length - 1, value));
  let matches: (label: string) => boolean;
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    // 日期边界包含该来源日的全部观测点，不把带时区的盘中边界截成日期。
    matches = (label) => /^\d{4}-\d{2}-\d{2}/.test(label) && (end ? label.slice(0, 10) <= value : label.slice(0, 10) >= value);
  } else if (/^\d{4}-\d{2}-\d{2}[T ]/.test(value) && Number.isFinite(Date.parse(value))) {
    const timestamp = Date.parse(value);
    matches = (label) => Number.isFinite(Date.parse(label)) && (end ? Date.parse(label) <= timestamp : Date.parse(label) >= timestamp);
  } else return labels.indexOf(value);
  if (!end) return labels.findIndex(matches);
  for (let index = labels.length - 1; index >= 0; index -= 1) if (matches(labels[index])) return index;
  return -1;
}

export function normalizeArtifactAnnotations(annotations: ArtifactAnnotation[], labels: string[]): ArtifactAnnotation[] {
  return annotations.flatMap((annotation) => {
    if (annotation.start === undefined || annotation.end === undefined) return [annotation];
    const start = boundaryIndex(labels, annotation.start, false);
    const end = boundaryIndex(labels, annotation.end, true);
    return start < 0 || end < start ? [] : [{ ...annotation, start: labels[start], end: labels[end] }];
  });
}

const FIELD_LABELS: Record<string, string> = {
  source: '来源', provider: '服务来源', as_of: '数据时间', observed_at: '获取时间', currency: '货币', frequency: '频率',
  time: '时间', date: '日期', open: '开盘价', close: '收盘价', high: '最高价', low: '最低价', volume: '成交量',
  kind: '方法', date_join: '日期对齐', baseline_date: '基准日期', end_date: '结束日期', base_value: '基准值', unit: '单位',
  price_basis: '价格口径', dividends_included: '是否计入股息', min_periods: '最少下跌期数', minimum_loss: '最低跌幅门槛',
  minimum_loss_unit: '跌幅单位', definition: '定义', return_start: '跌幅起点', overlap: '区间重叠', period_label: '周期日期', missing_periods: '缺失周期数',
};

const METHOD_VALUES: Record<string, string> = {
  price_return_comparison: '区间价格涨跌幅对比', consecutive_decline_streaks: '连续下跌区间统计',
  intersection: '共同交易日期', weekly: '周线', daily: '日线', monthly: '月线', '1wk': '周线', '1d': '日线',
  unknown: '未注明', split_adjusted_close: '拆股调整收盘价', unadjusted_close: '未复权收盘价', total_return: '总回报',
  ratio: '比例', last_observation: '周期最后一个观测点',
  "first declining period's previous close": '首个下跌周期之前一期的收盘价',
  'maximal non-overlapping consecutive streaks': '最大连续下跌区间，互不重叠',
};

export function artifactColumnLabel(artifact: ResearchArtifact, field: string): string {
  const series = artifact.spec?.series?.find((item) => item.field === field);
  return series ? `${series.name || FIELD_LABELS[field] || field}${series.unit ? `（${series.unit}）` : ''}` : FIELD_LABELS[field] || field;
}

export function artifactValueLabel(field: string, value: unknown): string {
  if (value === null || value === undefined) return field === 'dividends_included' || field === 'price_basis' ? '未注明' : '—';
  if (typeof value === 'string' && ['source', 'provider'].includes(field)) return sourceDisplayName(value);
  if (typeof value === 'string' && field === 'title') return sourceTitleDisplayName(value);
  if (typeof value === 'boolean') return value ? '是' : '否';
  return typeof value === 'string' && FIELD_LABELS[field] ? METHOD_VALUES[value] || value : String(value);
}

export function artifactMethodRows(method?: Record<string, unknown>) {
  return Object.entries(method ?? {}).filter(([field]) => FIELD_LABELS[field]).map(([field, value]) => ({
    label: FIELD_LABELS[field], value: artifactValueLabel(field, value),
  }));
}

export function buildArtifactChart(artifact: ResearchArtifact, dark: boolean, convention: 'intl' | 'cn' = 'intl', annotationNumbers?: number[]): EChartsOption | null {
  const rows = artifact.data?.rows;
  const spec = artifact.spec;
  if (!Array.isArray(rows) || !rows.length || !spec?.x || !Array.isArray(spec.series) || !spec.series.length) return null;
  const theme = artifactTheme(dark, convention);
  const { up, down, palette } = theme;
  const labels = rows.map((row) => String(row[spec.x!] ?? ''));
  const annotations = normalizeArtifactAnnotations(spec.annotations ?? [], labels);
  const windows = annotations.filter((annotation) => annotation.start !== undefined && annotation.end !== undefined);
  const dateLabels = labels.every((label) => /^\d{4}-\d{2}-\d{2}(?:[T ]00:00(?::00(?:\.0+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?$/.test(label));
  const isCandlestick = spec.chart_type === 'candlestick';
  const type = spec.chart_type === 'bar' ? 'bar' : spec.chart_type === 'scatter' ? 'scatter' : 'line';
  const windowTooltip = (payload: unknown): string => {
    const params = (Array.isArray(payload) ? payload : [payload]).filter((item) => item && typeof item === 'object') as Array<Record<string, unknown>>;
    const axisValue = String(params[0]?.axisValue ?? '');
    const index = labels.indexOf(axisValue);
    const values = params.map((item) => {
      const unit = spec.series!.find((series) => (series.name || series.field) === item.seriesName)?.unit || '';
      return `${item.seriesName || ''}：${item.value === null || item.value === undefined ? '—' : String(item.value)}${unit ? ` ${unit}` : ''}`;
    });
    const details = windows.flatMap((window, position) => index >= labels.indexOf(String(window.start)) && index <= labels.indexOf(String(window.end))
      ? [`区间${annotationNumbers?.[position] ?? position + 1} · ${window.label || ''}`, `${window.start} → ${window.end}`] : []);
    return [String(params[0]?.axisValueLabel || axisValue), ...values, ...details].join('\n');
  };
  const series = isCandlestick ? [{
    type: 'candlestick' as const, name: 'OHLC',
    data: rows.map((row) => ['open', 'close', 'low', 'high'].map((key) =>
      typeof row[key] === 'number' && Number.isFinite(row[key]) ? row[key] : null)),
    itemStyle: { color: up, color0: down, borderColor: up, borderColor0: down },
  }] : spec.series.map((item) => ({
    name: item.name || item.field, type,
    data: rows.map((row) => typeof row[item.field] === 'number' && Number.isFinite(row[item.field]) ? row[item.field] : null),
    showSymbol: false, connectNulls: false, lineStyle: { width: 1.6 },
    ...(spec.chart_type === 'area' ? { areaStyle: { opacity: 0.08 } } : {}),
    markLine: { silent: true, symbol: ['none', 'none'], data: annotations.filter((a) => typeof a.value === 'number' && Number.isFinite(a.value)).map((a) => ({ name: a.label, yAxis: a.value })) },
    markArea: { silent: false, label: { fontSize: 10, color: theme.text },
      itemStyle: { color: theme.downSoft },
      data: annotations.filter((a) => a.start !== undefined && a.end !== undefined)
        .map((a, index) => {
          const name = `区间${annotationNumbers?.[index] ?? index + 1}`;
          const description = `${name} · ${a.label || ''}\n${a.start} → ${a.end}`;
          return [{ name, xAxis: a.start, label: { position: 'insideTop', offset: [0, (index % 3) * 14] },
            tooltip: { trigger: 'item', formatter: description } }, { xAxis: a.end }];
        }) },
  }));
  return {
    color: palette, backgroundColor: 'transparent', animation: false,
    textStyle: { color: theme.text, fontFamily: 'system-ui' },
    tooltip: { trigger: 'axis', renderMode: 'richText', confine: true,
      ...(!isCandlestick && windows.length ? { formatter: windowTooltip } : {}) },
    legend: { bottom: 0, textStyle: { color: theme.text } },
    grid: { top: 20, left: 54, right: 24, bottom: 50 },
    xAxis: { type: 'category', data: labels, axisLabel: { color: theme.muted, fontSize: 10,
      ...(dateLabels ? { formatter: (value: string) => value.slice(0, 10) } : {}) }, axisLine: { lineStyle: { color: theme.border } } },
    yAxis: { type: spec.scale === 'log' ? 'log' : 'value', name: spec.series[0].unit || '',
      scale: true, axisLabel: { color: theme.muted, fontSize: 10 }, splitLine: { lineStyle: { color: theme.grid } } },
    ...(rows.length > 60 ? { dataZoom: [{ type: 'inside' }] } : {}),
    series,
  } as EChartsOption;
}

export function buildArtifactPanels(artifact: ResearchArtifact, dark: boolean, convention: 'intl' | 'cn' = 'intl') {
  const panels = artifact.data?.panels;
  if (!Array.isArray(panels)) return [];
  return panels.slice(0, 6).flatMap((panel) => {
    if (!panel || !Array.isArray(panel.rows) || !panel.rows.length || !artifact.spec) return [];
    const hasOHLC = panel.rows.every((row) => ['open', 'close', 'low', 'high'].every((key) => typeof row[key] === 'number' && Number.isFinite(row[key])));
    const requested = panel.chart_type || artifact.spec.chart_type;
    const chartType = requested === 'candlestick' && !hasOHLC ? 'line' : requested;
    const labels = panel.rows.map((row) => String(row[artifact.spec!.x || 'date']));
    const windows = (artifact.spec.annotations ?? []).filter((item) => item.start !== undefined && item.end !== undefined);
    const windowNumbers = windows.flatMap((item, index) => normalizeArtifactAnnotations([item], labels).length ? [index + 1] : []);
    const option = buildArtifactChart({ ...artifact, title: panel.title,
      spec: { ...artifact.spec, chart_type: chartType, scale: 'linear',
        annotations: normalizeArtifactAnnotations(artifact.spec.annotations ?? [], labels) },
      data: { rows: panel.rows },
    }, dark, convention, windowNumbers);
    if (!option) return [];
    const xAxis = option.xAxis as Record<string, unknown>;
    return [{ title: windowNumbers.length === 1 ? `区间${windowNumbers[0]} · ${panel.title}` : panel.title,
      baselineIncluded: panel.baseline_included === true, periods: panel.periods, option: { ...option, legend: { show: false },
      xAxis: { ...xAxis, axisLabel: { ...xAxis.axisLabel as Record<string, unknown>,
        interval: (index: number) => index === 0 || index === labels.length - 1, showMinLabel: true, showMaxLabel: true } },
      series: (option.series as Array<Record<string, unknown>>).map((series) => ({ ...series,
        ...(series.markArea ? { markArea: { ...series.markArea as Record<string, unknown>, label: { show: false } } } : {}) })),
      dataZoom: [], grid: { top: 12, right: 8, bottom: 24, left: 42 } } }];
  });
}
