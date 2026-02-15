/**
 * ECharts theme configuration for dark/light mode.
 *
 * Provides consistent color palettes, axis styles, and tooltip
 * appearance across all chart components.
 */

export const ECHARTS_DARK_COLORS = {
  bg: 'transparent',
  text: '#9ba1b0',
  textSecondary: '#6b7280',
  axisLine: '#2a2d38',
  splitLine: '#1e2028',
  success: '#0cad92',
  danger: '#f74f5c',
  warning: '#f5a623',
  primary: '#fa8019',
  series: ['#fa8019', '#0cad92', '#5b8def', '#f5a623', '#a78bfa', '#f74f5c'],
};

export const ECHARTS_LIGHT_COLORS = {
  bg: 'transparent',
  text: '#374151',
  textSecondary: '#6b7280',
  axisLine: '#e5e7eb',
  splitLine: '#f3f4f6',
  success: '#10b981',
  danger: '#ef4444',
  warning: '#f59e0b',
  primary: '#f97316',
  series: ['#f97316', '#10b981', '#3b82f6', '#f59e0b', '#8b5cf6', '#ef4444'],
};

export function getChartColors(isDark: boolean) {
  return isDark ? ECHARTS_DARK_COLORS : ECHARTS_LIGHT_COLORS;
}

export function getBaseChartOption(isDark: boolean) {
  const c = getChartColors(isDark);
  return {
    backgroundColor: c.bg,
    textStyle: {
      color: c.text,
      fontFamily: '-apple-system, "PingFang SC", "Microsoft YaHei", sans-serif',
    },
    title: { textStyle: { color: c.text } },
    legend: { textStyle: { color: c.textSecondary } },
    tooltip: {
      backgroundColor: isDark ? '#252830' : '#ffffff',
      borderColor: isDark ? '#2a2d38' : '#e5e7eb',
      textStyle: { color: isDark ? '#e8eaed' : '#1f2937' },
    },
    xAxis: {
      axisLine: { lineStyle: { color: c.axisLine } },
      splitLine: { lineStyle: { color: c.splitLine } },
      axisLabel: { color: c.textSecondary },
    },
    yAxis: {
      axisLine: { lineStyle: { color: c.axisLine } },
      splitLine: { lineStyle: { color: c.splitLine } },
      axisLabel: { color: c.textSecondary },
    },
    color: c.series,
  };
}
