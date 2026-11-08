import { useEffect, useMemo, useRef, useState } from 'react';
import { Download, Maximize2, Table2, X } from 'lucide-react';
import type { ECharts, EChartsOption } from 'echarts';
import EChart from '../charts/EChart';
import type { ResearchArtifact } from '../../types/runtime';
import { useStore } from '../../store/useStore';
import type { EvidenceItem } from '../../types';
import { sourceDisplayName, sourceTitleDisplayName } from '../../utils/sourceDisplayName';
import { chartSources, formatChartTimestamp } from '../../utils/chartSources';
import styles from './ChatDesign.module.css';

type ArtifactAnnotation = NonNullable<NonNullable<ResearchArtifact['spec']>['annotations']>[number];

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
  const green = dark ? '#4cc38a' : '#0f7a44';
  const red = dark ? '#ff7a7a' : '#c92a2a';
  const up = convention === 'cn' ? red : green;
  const down = convention === 'cn' ? green : red;
  const palette = dark ? ['#8098ff', '#4cc9d8', '#f2a74b', '#ad91ff'] : ['#3b5bdb', '#0b6e7f', '#a85400', '#6741d9'];
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
    markArea: { silent: false, label: { fontSize: 10, color: dark ? '#bcc2cd' : '#5c6879' },
      itemStyle: { color: dark ? 'rgba(255,122,122,.12)' : 'rgba(201,42,42,.08)' },
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
    textStyle: { color: dark ? '#bcc2cd' : '#5c6879', fontFamily: 'system-ui' },
    tooltip: { trigger: 'axis', renderMode: 'richText', confine: true,
      ...(!isCandlestick && windows.length ? { formatter: windowTooltip } : {}) },
    legend: { bottom: 0, textStyle: { color: dark ? '#bcc2cd' : '#5c6879' } },
    grid: { top: 20, left: 54, right: 24, bottom: 50 },
    xAxis: { type: 'category', data: labels, axisLabel: { color: dark ? '#939bab' : '#5c6879', fontSize: 10,
      ...(dateLabels ? { formatter: (value: string) => value.slice(0, 10) } : {}) }, axisLine: { lineStyle: { color: dark ? '#333b48' : '#e4e7ec' } } },
    yAxis: { type: spec.scale === 'log' ? 'log' : 'value', name: spec.series[0].unit || '',
      scale: true, axisLabel: { color: dark ? '#939bab' : '#5c6879', fontSize: 10 }, splitLine: { lineStyle: { color: dark ? '#252b35' : '#edf0f4' } } },
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

function exportRows(artifact: ResearchArtifact) {
  const rows = Array.isArray(artifact.data?.rows) ? artifact.data.rows.filter((row) => row && typeof row === 'object') : [];
  const columns = Array.from(new Set(rows.flatMap((row) => Object.keys(row))));
  const cell = (value: unknown) => {
    let text = value === null || value === undefined ? '' : String(value);
    if (typeof value === 'string' && /^[=+@-]/.test(text)) text = "'" + text;
    return '"' + text.replace(/"/g, '""') + '"';
  };
  const data = [columns.map(cell).join(','), ...rows.map((row) => columns.map((key) => cell(row[key])).join(','))].join('\r\n');
  const url = URL.createObjectURL(new Blob(['\ufeff' + data], { type: 'text/csv;charset=utf-8' }));
  const anchor = document.createElement('a'); anchor.href = url; anchor.download = artifact.artifact_id + '.csv'; anchor.click();
  URL.revokeObjectURL(url);
}

export function ResearchArtifactView({ artifact, sources = [] }: { artifact: ResearchArtifact; sources?: EvidenceItem[] }) {
  const dark = useStore((state) => state.theme === 'dark');
  const convention = useStore((state) => state.colorConvention);
  const [showData, setShowData] = useState(artifact.kind === 'table');
  const [expanded, setExpanded] = useState(false);
  const instance = useRef<ECharts | null>(null);
  const figure = useRef<HTMLElement | null>(null);
  useEffect(() => {
    if (!expanded) return;
    const previous = document.activeElement as HTMLElement | null;
    const controls = () => Array.from(figure.current?.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], [tabindex="0"]') ?? []);
    controls()[0]?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); setExpanded(false); }
      if (event.key !== 'Tab') return;
      const items = controls(); const first = items[0]; const last = items.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('keydown', onKey); previous?.focus(); };
  }, [expanded]);
  const option = useMemo(() => buildArtifactChart(artifact, dark, convention), [artifact, dark, convention]);
  const panels = useMemo(() => buildArtifactPanels(artifact, dark, convention), [artifact, dark, convention]);
  const rows = Array.isArray(artifact.data?.rows) ? artifact.data.rows.filter((row) => row && typeof row === 'object') : [];
  const columns = Array.from(new Set(rows.flatMap((row) => Object.keys(row)))).slice(0, 12);
  const usedSources = chartSources(artifact.source_refs, sources);
  const sourceNames = [...new Set(usedSources.map((source) => source.name))].join('、');
  const timestamps = [...new Set(usedSources.flatMap((source) => source.timestamps))];
  const asOf = timestamps.join('、') || formatChartTimestamp(typeof artifact.method?.as_of === 'string' ? artifact.method.as_of : undefined);
  const code = typeof artifact.method?.code === 'string' ? artifact.method.code : '';
  const methodRows = artifactMethodRows(artifact.method);
  const windows = (artifact.spec?.annotations ?? []).filter((item) => item.start !== undefined && item.end !== undefined);
  return <figure ref={figure} role={expanded ? 'dialog' : undefined} aria-modal={expanded || undefined} className={`research-artifact ${styles.artifact} ${expanded ? 'research-artifact-expanded' : ''}`} aria-label={artifact.title}>
    <div className="research-artifact-header">
      <figcaption className={`min-w-0 flex-1 ${styles.artifactTitle}`}>{artifact.title}
        {(sourceNames || asOf) && <p className={styles.artifactSubtitle}>{[sourceNames, asOf].filter(Boolean).join(' · ')}</p>}</figcaption>
      <button type="button" onClick={() => setShowData(!showData)} className="artifact-action" aria-pressed={showData} title="查看数据"><Table2 size={15} /><span>数据</span></button>
      <button type="button" onClick={() => {
        if (showData || !instance.current) exportRows(artifact);
        else { const a = document.createElement('a'); a.href = instance.current.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: dark ? '#0e1014' : '#fff' }); a.download = artifact.artifact_id + '.png'; a.click(); }
      }} disabled={!rows.length} className="artifact-action" title={panels.length && !showData ? '下载主图' : '下载图表或数据'}><Download size={15} /><span>{panels.length && !showData ? '下载主图' : '下载'}</span></button>
      <button type="button" className="artifact-action" aria-label={expanded ? '收起图表' : '放大图表'} onClick={() => setExpanded(!expanded)}>
        {expanded ? <X size={15} /> : <Maximize2 size={15} />}
      </button>
    </div>
    {showData ? <div className="max-h-[420px] overflow-auto p-3"><table className="w-full text-xs">
      <thead><tr>{columns.map((key) => <th className="border-b border-t-border px-3 py-2 text-left font-medium" key={key}>{artifactColumnLabel(artifact, key)}</th>)}</tr></thead>
      <tbody>{rows.slice(0, 200).map((row, i) => <tr key={i}>{columns.map((key) => <td key={key} className="border-b border-t-divider px-3 py-2 num">{artifactValueLabel(key, row[key])}</td>)}</tr>)}</tbody>
    </table>{rows.length > 200 && <p className="pt-3 text-t-text3">显示前200行；下载包含完整数据。</p>}</div>
      : option ? <><EChart option={option} onChartReady={(chart) => { instance.current = chart; }} style={{ height: expanded ? '55vh' : 'clamp(220px,32vw,292px)' }} />
          {windows.length > 0 && <details className="border-t border-t-divider px-4 py-2 text-xs text-t-text3">
            <summary className="cursor-pointer">{windows.length} 个区间 · 编号对应主图</summary>
            <ol className="mt-2 grid gap-2 sm:grid-cols-2">{windows.map((window, index) => <li key={index}>
              <span className="font-medium text-t-text">区间{index + 1}</span> · {window.label}<br />{String(window.start)} → {String(window.end)}
            </li>)}</ol>
          </details>}
          {panels.length > 0 && <><p className="px-4 pb-1 pt-2 text-xs text-t-text3">各区间独立纵轴，展示各自的实际价格。</p><div className={styles.artifactPanels} aria-label="历史区间对照">
            {panels.map((panel, index) => <section key={panel.title + ':' + index} className="min-w-0 overflow-hidden rounded-lg border border-t-border px-2 pt-2" aria-label={panel.title}>
              <h4 className="px-1 text-xs font-medium text-t-text">{panel.title}</h4>
              {panel.baselineIncluded && <p className="px-1 text-[11px] text-t-text3">含前一期基准{typeof panel.periods === 'number' ? ` · ${panel.periods} 个下跌周期` : ''}</p>}
              <EChart option={panel.option} style={{ height: 110 }} />
            </section>)}
          </div></>}
          {(artifact.data?.panels?.length ?? 0) > 6 && <p className="px-4 pb-3 text-xs text-t-text3">展示前6个区间，其余区间可查看完整数据。</p>}
        </>
        : <p className="p-5 text-sm text-t-text3">暂无可绘图的数据。</p>}
    <div className="border-t border-t-divider px-4 py-2 text-xs leading-5 text-t-text3">
      {artifact.spec?.scale === 'log' && <span className="mr-3">对数坐标</span>}
      {typeof artifact.method?.frequency === 'string' && <span className="mr-3">{artifactValueLabel('frequency', artifact.method.frequency)}</span>}
      {(artifact.limitations ?? []).map((item) => <p key={item}>{item}</p>)}
      {usedSources.length > 0 && <span>{usedSources.length} 个数据来源</span>}
      {!usedSources.length && (artifact.source_refs?.length ?? 0) > 0 && <span>数据来源未注明</span>}
      {(sourceNames || asOf) && <p>{[sourceNames, asOf].filter(Boolean).join(' · ')}</p>}
      <details className="mt-2"><summary className="cursor-pointer">查看代码和数据</summary>
        {methodRows.length > 0 && <table className={`${styles.detailTable} mt-2`}><tbody>{methodRows.map((row) => <tr key={row.label}>
          <th>{row.label}</th><td>{row.value}</td></tr>)}</tbody></table>}
        {code && <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-t-bg p-3 font-mono text-xs">{code}</pre>}
        {typeof artifact.method?.description === 'string' && <p>{artifact.method.description}</p>}
        <button type="button" className="mt-2 text-t-accent" onClick={() => setShowData(true)}>查看数据（{rows.length} 行）</button>
        {!code && <p className="mt-1">没有附上计算代码。</p>}
      </details>
    </div>
  </figure>;
}

