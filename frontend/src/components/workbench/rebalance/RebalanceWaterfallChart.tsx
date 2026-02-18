/**
 * RebalanceWaterfallChart - Waterfall chart showing weight changes per ticker.
 *
 * Displays current_weight → delta_weight → target_weight for each action.
 * Green for increase, red for decrease.
 */
import { useMemo } from 'react';
import ReactECharts from 'echarts-for-react';

import { useChartTheme } from '../../../hooks/useChartTheme';
import type { RebalanceAction } from '../../../types/dashboard';

// --- Props ---

interface RebalanceWaterfallChartProps {
  actions: RebalanceAction[];
}

// --- Component ---

export function RebalanceWaterfallChart({ actions }: RebalanceWaterfallChartProps) {
  const theme = useChartTheme();

  const option = useMemo(() => {
    if (!actions || actions.length === 0) return null;

    // Sort by priority for consistent ordering
    const sorted = [...actions].sort((a, b) => a.priority - b.priority);

    const tickers = sorted.map((a) => a.ticker);
    const currentWeights = sorted.map((a) => a.current_weight);
    const targetWeights = sorted.map((a) => a.target_weight);
    const deltas = sorted.map((a) => a.delta_weight);

    return {
      tooltip: {
        trigger: 'axis' as const,
        backgroundColor: theme.tooltipBackground,
        borderColor: theme.tooltipBorder,
        textStyle: { color: theme.tooltipText, fontSize: 11 },
        formatter: (params: Array<{ seriesName: string; value: number; axisValue: string; marker: string }>) => {
          const ticker = params[0]?.axisValue ?? '';
          const idx = tickers.indexOf(ticker);
          if (idx < 0) return '';
          const cur = currentWeights[idx];
          const tgt = targetWeights[idx];
          const delta = deltas[idx];
          const sign = delta >= 0 ? '+' : '';
          return `<div style="font-size:11px"><b>${ticker}</b><br/>` +
            `当前: ${cur.toFixed(1)}%<br/>` +
            `目标: ${tgt.toFixed(1)}%<br/>` +
            `变动: ${sign}${delta.toFixed(1)}%</div>`;
        },
      },
      grid: { left: 56, right: 16, top: 8, bottom: 24 },
      xAxis: {
        type: 'category' as const,
        data: tickers,
        axisLabel: { color: theme.muted, fontSize: 10, rotate: tickers.length > 8 ? 30 : 0 },
        axisLine: { lineStyle: { color: theme.border } },
      },
      yAxis: {
        type: 'value' as const,
        axisLabel: { color: theme.muted, fontSize: 9, formatter: '{value}%' },
        splitLine: { lineStyle: { color: theme.grid, type: 'dashed' } },
      },
      series: [
        {
          name: '当前权重',
          type: 'bar',
          stack: 'weight',
          data: currentWeights.map((v) => ({
            value: v,
            itemStyle: { color: theme.primarySoft, borderRadius: [0, 0, 0, 0] },
          })),
          barMaxWidth: 32,
        },
        {
          name: '变动',
          type: 'bar',
          stack: 'weight',
          data: deltas.map((d) => ({
            value: d,
            itemStyle: {
              color: d >= 0 ? theme.success : theme.danger,
              borderRadius: d >= 0 ? [3, 3, 0, 0] : [0, 0, 3, 3],
              opacity: 0.85,
            },
          })),
          barMaxWidth: 32,
          label: {
            show: true,
            position: 'top',
            fontSize: 9,
            color: theme.muted,
            formatter: (params: { value: number }) => {
              const v = params.value;
              if (Math.abs(v) < 0.1) return '';
              return `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`;
            },
          },
        },
      ],
    };
  }, [actions, theme]);

  if (!option) return null;

  const chartHeight = Math.max(160, Math.min(actions.length * 28 + 60, 300));

  return (
    <div className="p-3 bg-fin-card/50 rounded-lg border border-fin-border/50">
      <div className="text-xs font-medium text-fin-muted mb-2">权重变化可视化</div>
      <ReactECharts
        option={option}
        style={{ width: '100%', height: chartHeight }}
        opts={{ renderer: 'svg' }}
        notMerge
        lazyUpdate
      />
      <div className="flex items-center gap-4 mt-2 text-2xs text-fin-muted">
        <span className="flex items-center gap-1">
          <span className="inline-block w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: theme.primarySoft }} />
          当前权重
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: theme.success }} />
          增持
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: theme.danger }} />
          减持
        </span>
      </div>
    </div>
  );
}

export default RebalanceWaterfallChart;
