/**
 * EarningsSurpriseChart - EPS estimate vs actual grouped bar chart.
 *
 * Shows quarterly EPS surprise with estimate/actual grouped bars
 * and surprise percentage line overlay.
 * Green = beat estimate, Red = missed estimate.
 */
import { useMemo } from 'react';
import ReactECharts from 'echarts-for-react';

import { useChartTheme } from '../../../../hooks/useChartTheme';
import type { EarningsHistoryEntry } from '../../../../types/dashboard';

// --- Props ---

interface EarningsSurpriseChartProps {
  data?: EarningsHistoryEntry[] | null;
}

// --- Component ---

export function EarningsSurpriseChart({ data }: EarningsSurpriseChartProps) {
  const theme = useChartTheme();

  const option = useMemo(() => {
    if (!data || data.length === 0) return null;

    // Take last 8 quarters, sorted chronologically
    const sorted = [...data].slice(-8);
    const quarters = sorted.map((e) => e.quarter);
    const estimates = sorted.map((e) => e.eps_estimate ?? null);
    const actuals = sorted.map((e) => e.eps_actual ?? null);
    const surprises = sorted.map((e) =>
      e.surprise_pct != null ? Math.round(e.surprise_pct * 100) / 100 : null,
    );

    return {
      tooltip: {
        trigger: 'axis' as const,
        axisPointer: { type: 'shadow' },
        backgroundColor: theme.tooltipBackground,
        borderColor: theme.tooltipBorder,
        textStyle: { color: theme.tooltipText, fontSize: 11 },
      },
      legend: {
        data: ['预期 EPS', '实际 EPS', '惊喜率'],
        textStyle: { color: theme.muted, fontSize: 10 },
        top: 0,
        itemWidth: 12,
        itemHeight: 8,
      },
      grid: { left: 48, right: 48, top: 32, bottom: 8, containLabel: false },
      xAxis: {
        type: 'category' as const,
        data: quarters,
        axisLine: { lineStyle: { color: theme.border } },
        axisLabel: { color: theme.muted, fontSize: 9, rotate: 30 },
      },
      yAxis: [
        {
          type: 'value' as const,
          axisLabel: { color: theme.muted, fontSize: 9, formatter: '${value}' },
          splitLine: { lineStyle: { color: theme.grid, type: 'dashed' } },
        },
        {
          type: 'value' as const,
          axisLabel: { color: theme.muted, fontSize: 9, formatter: '{value}%' },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: '预期 EPS',
          type: 'bar',
          data: estimates,
          barMaxWidth: 16,
          itemStyle: { color: theme.primarySoft, borderRadius: [2, 2, 0, 0] },
        },
        {
          name: '实际 EPS',
          type: 'bar',
          data: actuals?.map((v, i) => ({
            value: v,
            itemStyle: {
              color: v != null && estimates[i] != null && v >= (estimates[i] ?? 0)
                ? theme.success
                : theme.danger,
              borderRadius: [2, 2, 0, 0],
            },
          })),
          barMaxWidth: 16,
        },
        {
          name: '惊喜率',
          type: 'line',
          yAxisIndex: 1,
          data: surprises,
          smooth: true,
          showSymbol: true,
          symbolSize: 5,
          lineStyle: { color: theme.warning, width: 2 },
          itemStyle: { color: theme.warning },
        },
      ],
    };
  }, [data, theme]);

  if (!option) {
    return (
      <div className="p-4 bg-fin-card rounded-xl border border-fin-border">
        <div className="text-xs font-medium text-fin-muted mb-3">EPS 预期 vs 实际</div>
        <div className="text-sm text-fin-muted">暂无盈利数据</div>
      </div>
    );
  }

  return (
    <div className="p-4 bg-fin-card rounded-xl border border-fin-border">
      <div className="text-xs font-medium text-fin-muted mb-2">EPS 预期 vs 实际</div>
      <ReactECharts
        option={option}
        style={{ width: '100%', height: 240 }}
        opts={{ renderer: 'svg' }}
        notMerge
        lazyUpdate
      />
    </div>
  );
}

export default EarningsSurpriseChart;
