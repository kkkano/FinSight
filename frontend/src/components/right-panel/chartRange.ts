import type { SmartChartData } from '../SmartChart';

export const CHART_RANGES = [
  { value: '1m', label: '1 月', months: 1 },
  { value: '3m', label: '3 月', months: 3 },
  { value: '6m', label: '6 月', months: 6 },
  { value: '1y', label: '1 年', months: 12 },
] as const;

export type ChartRange = typeof CHART_RANGES[number]['value'];

export function selectChartRange(data: SmartChartData, range: ChartRange): SmartChartData {
  if (data.labels.length === 0) return data;
  const last = new Date(data.labels.at(-1)!.slice(0, 10));
  if (!Number.isFinite(last.getTime())) return data;
  const months = CHART_RANGES.find((item) => item.value === range)!.months;
  const firstOfMonth = new Date(Date.UTC(last.getUTCFullYear(), last.getUTCMonth() - months, 1));
  const lastDayOfMonth = new Date(Date.UTC(firstOfMonth.getUTCFullYear(), firstOfMonth.getUTCMonth() + 1, 0)).getUTCDate();
  const cutoff = new Date(Date.UTC(firstOfMonth.getUTCFullYear(), firstOfMonth.getUTCMonth(), Math.min(last.getUTCDate(), lastDayOfMonth))).toISOString().slice(0, 10);
  // 从最后一个真实交易日回看，周末和数据延迟不会生成额外行情。
  const start = data.labels.findIndex((label) => label.slice(0, 10) >= cutoff);
  if (start <= 0) return data;
  return {
    ...data,
    labels: data.labels.slice(start),
    values: data.values.slice(start),
    ohlc: data.ohlc?.slice(start),
    volume: data.volume?.slice(start),
  };
}
