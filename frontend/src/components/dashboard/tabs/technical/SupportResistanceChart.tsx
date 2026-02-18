/**
 * SupportResistanceChart - K-line candlestick chart with support/resistance levels.
 *
 * Replaces the old CSS bar version with a real ECharts candlestick chart.
 * Support levels shown as green horizontal lines, resistance as red.
 * DataZoom allows zooming into specific date ranges.
 */
import { useMemo } from 'react';
import ReactECharts from 'echarts-for-react';

import { useChartTheme, type ChartTheme } from '../../../../hooks/useChartTheme';
import type { ChartPoint, TechnicalData } from '../../../../types/dashboard';

// --- Props ---

interface SupportResistanceChartProps {
  technicals?: TechnicalData | null;
  marketChart?: ChartPoint[];
}

// --- Helpers ---

interface MarkLineEntry {
  yAxis: number;
  lineStyle: { color: string; type: string; width: number };
  label: { formatter: string; position: string; fontSize: number };
}

const buildLevelLines = (
  levels: number[],
  type: 'support' | 'resistance',
  theme: ChartTheme,
): MarkLineEntry[] =>
  levels.map((value) => ({
    yAxis: value,
    lineStyle: {
      color: type === 'support' ? theme.success : theme.danger,
      type: 'dashed',
      width: 1.5,
    },
    label: {
      formatter: `${type === 'support' ? 'S' : 'R'} ${value.toFixed(2)}`,
      position: 'insideEndTop',
      fontSize: 10,
    },
  }));

const formatDate = (point: ChartPoint): string => {
  if (point.time) {
    const d = new Date(point.time * 1000);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  }
  return point.period ?? '';
};

// --- Component ---

export function SupportResistanceChart({ technicals, marketChart }: SupportResistanceChartProps) {
  const theme = useChartTheme();

  const option = useMemo(() => {
    if (!marketChart || marketChart.length === 0) return null;

    // Take last 120 data points for readability
    const slice = marketChart.slice(-120);

    const dates = slice.map(formatDate);
    const ohlc = slice.map((p) => [p.open ?? 0, p.close ?? 0, p.low ?? 0, p.high ?? 0]);
    const volumes = slice.map((p) => p.volume ?? 0);

    const supportLevels = technicals?.support_levels ?? [];
    const resistanceLevels = technicals?.resistance_levels ?? [];

    return {
      animation: true,
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        backgroundColor: theme.tooltipBackground,
        borderColor: theme.tooltipBorder,
        textStyle: { color: theme.tooltipText, fontSize: 11 },
      },
      grid: [
        { left: 60, right: 16, top: 24, bottom: 80 },
        { left: 60, right: 16, top: '72%', bottom: 32 },
      ],
      xAxis: [
        {
          type: 'category',
          data: dates,
          axisLine: { lineStyle: { color: theme.border } },
          axisLabel: { color: theme.muted, fontSize: 10, rotate: 0 },
          splitLine: { show: false },
          gridIndex: 0,
        },
        {
          type: 'category',
          data: dates,
          gridIndex: 1,
          axisLabel: { show: false },
          axisLine: { show: false },
          axisTick: { show: false },
        },
      ],
      yAxis: [
        {
          type: 'value',
          scale: true,
          gridIndex: 0,
          axisLabel: { color: theme.muted, fontSize: 10 },
          splitLine: { lineStyle: { color: theme.grid, type: 'dashed' } },
        },
        {
          type: 'value',
          scale: true,
          gridIndex: 1,
          axisLabel: { show: false },
          splitLine: { show: false },
        },
      ],
      dataZoom: [
        {
          type: 'inside',
          xAxisIndex: [0, 1],
          start: 60,
          end: 100,
        },
        {
          type: 'slider',
          xAxisIndex: [0, 1],
          bottom: 8,
          height: 18,
          borderColor: theme.border,
          fillerColor: theme.sliderFiller,
          handleStyle: { color: theme.primary },
          textStyle: { color: theme.muted, fontSize: 10 },
        },
      ],
      series: [
        {
          name: 'K线',
          type: 'candlestick',
          data: ohlc,
          xAxisIndex: 0,
          yAxisIndex: 0,
          itemStyle: {
            color: theme.success,
            color0: theme.danger,
            borderColor: theme.success,
            borderColor0: theme.danger,
          },
          markLine: {
            symbol: 'none',
            silent: true,
            data: [
              ...buildLevelLines(supportLevels, 'support', theme),
              ...buildLevelLines(resistanceLevels, 'resistance', theme),
            ],
          },
        },
        {
          name: '成交量',
          type: 'bar',
          data: volumes,
          xAxisIndex: 1,
          yAxisIndex: 1,
          itemStyle: {
            color: theme.primarySoft,
          },
          barMaxWidth: 6,
        },
      ],
    };
  }, [marketChart, technicals, theme]);

  if (!option) {
    return (
      <div className="p-4 bg-fin-card rounded-xl border border-fin-border">
        <div className="text-xs font-medium text-fin-muted mb-3">支撑/阻力位</div>
        <div className="text-sm text-fin-muted">暂无K线数据</div>
      </div>
    );
  }

  return (
    <div className="p-4 bg-fin-card rounded-xl border border-fin-border">
      <div className="text-xs font-medium text-fin-muted mb-2">K线图 · 支撑/阻力位</div>
      <ReactECharts
        option={option}
        style={{ width: '100%', height: 360 }}
        opts={{ renderer: 'svg' }}
        notMerge
        lazyUpdate
      />
    </div>
  );
}

export default SupportResistanceChart;
