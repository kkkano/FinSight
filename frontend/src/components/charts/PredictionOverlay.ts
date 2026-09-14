import type { PredictionOverlay } from '../../types/chartPrediction';

type ChartSeriesOption = Record<string, unknown> & { data?: unknown };
type ChartOption = Record<string, unknown> & { series?: ChartSeriesOption[] };

export interface PredictionAnnotations {
  markLine?: Record<string, unknown>;
  markPoint?: Record<string, unknown>;
  markArea?: Record<string, unknown>;
}

const RESOLVED_STATUSES = new Set([
  'hit_target',
  'hit_stop',
  'held_range',
  'broke_range',
]);

export const STATUS_SUFFIX: Record<PredictionOverlay['status'], string> = {
  waiting: '等待',
  open: '生效',
  triggered: '已触发',
  invalidated: '已失效',
  hit_target: '已达目标',
  hit_stop: '已止损',
  held_range: '区间成立',
  broke_range: '区间突破',
};

function levelColor(kind: 'entry' | 'stop' | 'target'): string {
  if (kind === 'stop') return '#ef4444';
  if (kind === 'target') return '#22c55e';
  return '#f59e0b';
}

function toDateKey(value: string): string | null {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  return [
    parsed.getFullYear(),
    String(parsed.getMonth() + 1).padStart(2, '0'),
    String(parsed.getDate()).padStart(2, '0'),
  ].join('-');
}

function findAnchorIndex(labels: string[], anchorTime: string): number {
  const exact = labels.indexOf(anchorTime);
  if (exact >= 0) return exact;
  const anchorDate = toDateKey(anchorTime);
  return anchorDate
    ? labels.findIndex((label) => toDateKey(label) === anchorDate)
    : -1;
}

function buildLevelLine(
  name: string,
  value: number | undefined,
  kind: 'entry' | 'stop' | 'target',
  prediction: PredictionOverlay,
) {
  if (value === undefined) return null;
  const terminal = prediction.status === 'invalidated' || RESOLVED_STATUSES.has(prediction.status);
  return {
    name,
    yAxis: value,
    lineStyle: {
      color: levelColor(kind),
      type: terminal ? 'dashed' : 'solid',
      opacity: prediction.status === 'invalidated' ? 0.55 : 0.9,
    },
    label: {
      show: true,
      formatter: `${name} ${value} · ${STATUS_SUFFIX[prediction.status]}`,
      color: levelColor(kind),
      fontSize: 10,
    },
  };
}

/** 只生成 ECharts 标注对象，不接收也不返回任何行情 data。 */
export function buildPredictionAnnotations(
  prediction: PredictionOverlay,
  labels: string[],
): PredictionAnnotations {
  const anchorIndex = findAnchorIndex(labels, prediction.anchor.time);
  const anchorLabel = anchorIndex >= 0 ? labels[anchorIndex] : prediction.anchor.time;
  const nextLabel = anchorIndex >= 0 ? labels[Math.min(anchorIndex + 1, labels.length - 1)] : anchorLabel;
  const markLineData = [
    buildLevelLine('入场', prediction.entry, 'entry', prediction),
    buildLevelLine('止损', prediction.stop, 'stop', prediction),
    buildLevelLine('T1', prediction.target1, 'target', prediction),
    buildLevelLine('T2', prediction.target2, 'target', prediction),
  ].filter(Boolean);

  const markAreaData: unknown[] = [
    [
      { name: 'AI 锚点', xAxis: anchorLabel, itemStyle: { color: 'rgba(245, 158, 11, 0.10)' } },
      { xAxis: nextLabel },
    ],
  ];

  if (prediction.range) {
    markAreaData.push([
      { name: '中性区间', yAxis: prediction.range.low, itemStyle: { color: 'rgba(59, 130, 246, 0.10)' } },
      { yAxis: prediction.range.high },
    ]);
  }
  for (const zone of prediction.zones ?? []) {
    markAreaData.push([
      { name: zone.label, yAxis: zone.low, itemStyle: { color: 'rgba(139, 92, 246, 0.10)' } },
      { yAxis: zone.high },
    ]);
  }

  return {
    markPoint: {
      symbol: 'pin',
      symbolSize: 38,
      data: [{
        name: 'AI 锚点',
        coord: [anchorLabel, prediction.anchor.price],
        value: prediction.anchor.price,
        itemStyle: { color: '#f59e0b' },
        label: { color: '#111827', fontSize: 9, formatter: 'AI' },
      }],
    },
    ...(markLineData.length > 0
      ? { markLine: { symbol: 'none', silent: true, data: markLineData } }
      : {}),
    markArea: { silent: true, label: { show: false }, data: markAreaData },
  };
}

/**
 * 把 AI 标注合并到第一条真实行情 series；所有 series.data 保持原引用与原值。
 * prediction 即便曾夹带行情字段，也已在 normalizePredictionOverlay 阶段被白名单丢弃。
 */
export function applyPredictionOverlay(
  marketOption: ChartOption,
  prediction: PredictionOverlay | null,
  labels: string[],
): ChartOption {
  if (!prediction || !Array.isArray(marketOption.series) || marketOption.series.length === 0) {
    return marketOption;
  }

  const annotations = buildPredictionAnnotations(prediction, labels);
  const series = marketOption.series.map((item, index) => {
    if (index !== 0) return item;
    const merged = { ...item };
    for (const key of ['markLine', 'markPoint', 'markArea'] as const) {
      const existing = item[key];
      const incoming = annotations[key];
      if (!incoming) continue;
      const existingAnnotation = existing && typeof existing === 'object' && !Array.isArray(existing)
        ? existing as Record<string, unknown>
        : {};
      const existingData = Array.isArray(existingAnnotation.data) ? existingAnnotation.data : [];
      const incomingData = Array.isArray(incoming.data) ? incoming.data : [];
      merged[key] = {
        ...existingAnnotation,
        ...incoming,
        data: [...existingData, ...incomingData],
      };
    }
    return merged;
  });

  return {
    ...marketOption,
    series,
  };
}
