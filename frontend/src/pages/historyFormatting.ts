export function formatPercentagePoints(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '--';
  return `${value.toFixed(1)}%`;
}

export function formatRatioPercent(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '--';
  return formatPercentagePoints(value * 100);
}
