/**
 * ValuationBarChart - ECharts horizontal bar chart for PE comparison.
 *
 * Replaces the old CSS div-width version with a real ECharts horizontal bar.
 * Current stock is highlighted with primary color.
 */
import { useMemo } from 'react';
import ReactECharts from 'echarts-for-react';

import { useChartTheme } from '../../../../hooks/useChartTheme';
import type { PeerMetrics } from '../../../../types/dashboard';

// --- Props ---

interface ValuationBarChartProps {
  peers: PeerMetrics[];
  subjectSymbol: string;
}

// --- Component ---

export function ValuationBarChart({ peers, subjectSymbol }: ValuationBarChartProps) {
  const theme = useChartTheme();

  const option = useMemo(() => {
    const withPE = peers
      .filter((p) => p.trailing_pe != null && p.trailing_pe > 0)
      .map((p) => ({
        symbol: p.symbol,
        value: p.trailing_pe as number,
        isCurrent: p.symbol.toUpperCase() === subjectSymbol.toUpperCase(),
      }))
      .sort((a, b) => a.value - b.value); // ascending for horizontal bar

    if (withPE.length === 0) return null;

    const symbols = withPE.map((d) => d.symbol);
    const values = withPE.map((d) => d.value);
    const colors = withPE.map((d) => (d.isCurrent ? theme.warning : theme.primarySoft));

    return {
      tooltip: {
        trigger: 'axis' as const,
        axisPointer: { type: 'shadow' },
        backgroundColor: theme.tooltipBackground,
        borderColor: theme.tooltipBorder,
        textStyle: { color: theme.tooltipText, fontSize: 11 },
        formatter: (params: Array<{ name: string; value: number }>) => {
          const p = params[0];
          return p ? `<b>${p.name}</b><br/>P/E: ${p.value.toFixed(1)}x` : '';
        },
      },
      grid: { left: 56, right: 40, top: 8, bottom: 8 },
      xAxis: {
        type: 'value' as const,
        axisLabel: { color: theme.muted, fontSize: 9, formatter: '{value}x' },
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
          fontWeight: 'normal' as const,
        },
      },
      series: [
        {
          type: 'bar',
          data: values.map((v, i) => ({
            value: v,
            itemStyle: { color: colors[i], borderRadius: [0, 3, 3, 0] },
          })),
          barMaxWidth: 18,
          label: {
            show: true,
            position: 'right' as const,
            formatter: (p: { value: number }) => `${p.value.toFixed(1)}`,
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
        暂无市盈率数据
      </div>
    );
  }

  const chartHeight = Math.max(120, option.yAxis.data.length * 32 + 24);

  return (
    <div className="bg-fin-card border border-fin-border rounded-lg p-4">
      <h4 className="text-sm font-semibold text-fin-text mb-2">P/E 对比</h4>
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

export default ValuationBarChart;
