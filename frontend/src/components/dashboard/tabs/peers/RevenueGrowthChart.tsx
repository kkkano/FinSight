/**
 * RevenueGrowthChart - ECharts diverging horizontal bar chart for revenue growth.
 *
 * Replaces the old CSS bidirectional bar version with a real ECharts chart.
 * Positive growth extends right (green), negative extends left (red).
 * Current stock is highlighted.
 */
import { useMemo } from 'react';
import ReactECharts from 'echarts-for-react';

import { useChartTheme } from '../../../../hooks/useChartTheme';
import type { PeerMetrics } from '../../../../types/dashboard';

// --- Props ---

interface RevenueGrowthChartProps {
  peers: PeerMetrics[];
  subjectSymbol: string;
}

// --- Component ---

export function RevenueGrowthChart({ peers, subjectSymbol }: RevenueGrowthChartProps) {
  const theme = useChartTheme();

  const option = useMemo(() => {
    const withGrowth = peers
      .filter((p) => p.revenue_growth != null)
      .map((p) => ({
        symbol: p.symbol,
        value: Math.round((p.revenue_growth as number) * 1000) / 10,
        isCurrent: p.symbol.toUpperCase() === subjectSymbol.toUpperCase(),
      }))
      .sort((a, b) => a.value - b.value); // ascending for horizontal bar

    if (withGrowth.length === 0) return null;

    const symbols = withGrowth.map((d) => d.symbol);

    return {
      tooltip: {
        trigger: 'axis' as const,
        axisPointer: { type: 'shadow' },
        backgroundColor: theme.tooltipBackground,
        borderColor: theme.tooltipBorder,
        textStyle: { color: theme.tooltipText, fontSize: 11 },
        formatter: (params: Array<{ name: string; value: number }>) => {
          const p = params[0];
          if (!p) return '';
          const sign = p.value >= 0 ? '+' : '';
          return `<b>${p.name}</b><br/>营收增长: ${sign}${p.value.toFixed(1)}%`;
        },
      },
      grid: { left: 56, right: 48, top: 8, bottom: 8 },
      xAxis: {
        type: 'value' as const,
        axisLabel: {
          color: theme.muted,
          fontSize: 9,
          formatter: (v: number) => `${v >= 0 ? '+' : ''}${v}%`,
        },
        splitLine: { lineStyle: { color: theme.grid, type: 'dashed' } },
      },
      yAxis: {
        type: 'category' as const,
        data: symbols,
        axisLine: { lineStyle: { color: theme.border } },
        axisLabel: {
          color: (value: string) =>
            value.toUpperCase() === subjectSymbol.toUpperCase() ? theme.primary : theme.muted,
          fontSize: 10,
        },
      },
      series: [
        {
          type: 'bar',
          data: withGrowth.map((d) => ({
            value: d.value,
            itemStyle: {
              color: d.isCurrent
                ? (d.value >= 0 ? theme.warning : theme.danger)
                : (d.value >= 0 ? theme.success : theme.danger),
              opacity: d.isCurrent ? 1 : 0.5,
              borderRadius: d.value >= 0 ? [0, 3, 3, 0] : [3, 0, 0, 3],
            },
          })),
          barMaxWidth: 18,
          label: {
            show: true,
            position: 'right' as const,
            formatter: (p: { value: number }) => {
              const sign = p.value >= 0 ? '+' : '';
              return `${sign}${p.value.toFixed(1)}%`;
            },
            fontSize: 9,
            color: theme.textSecondary,
          },
        },
      ],
    };
  }, [peers, subjectSymbol, theme]);

  if (!option) {
    return (
      <div className="flex items-center justify-center h-32 text-fin-muted text-sm">
        暂无营收增长数据
      </div>
    );
  }

  const chartHeight = Math.max(120, option.yAxis.data.length * 32 + 24);

  return (
    <div className="bg-fin-card border border-fin-border rounded-lg p-4">
      <h4 className="text-sm font-semibold text-fin-text mb-2">营收增长对比</h4>
      <ReactECharts
        option={option}
        style={{ width: '100%', height: chartHeight }}
        opts={{ renderer: 'svg' }}
        notMerge
        lazyUpdate
      />
    </div>
  );
}

export default RevenueGrowthChart;
