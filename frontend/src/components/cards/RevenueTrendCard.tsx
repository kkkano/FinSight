import ReactECharts from 'echarts-for-react';
import { useChartTheme } from '../../hooks/useChartTheme';
import type { ChartPoint } from '../../types/dashboard';

interface RevenueTrendCardProps {
  data: ChartPoint[];
  loading?: boolean;
  title?: string;
}

export function RevenueTrendCard({ data, loading, title = '营收趋势' }: RevenueTrendCardProps) {
  const chartTheme = useChartTheme();

  if (loading) {
    return (
      <div className="bg-fin-card border border-fin-border rounded-xl p-4 h-64">
        <div className="h-4 bg-fin-border rounded w-24 mb-4" />
        <div className="h-48 bg-fin-border rounded animate-pulse" />
      </div>
    );
  }

  if (!data || data.length === 0) {
    return (
      <div className="bg-fin-card border border-fin-border rounded-xl p-4 h-64 flex items-center justify-center text-fin-muted text-sm">
        暂无营收数据
      </div>
    );
  }

  const formatValue = (value: number) => {
    if (value >= 1e9) return `${(value / 1e9).toFixed(1)}B`;
    if (value >= 1e6) return `${(value / 1e6).toFixed(1)}M`;
    return value.toLocaleString();
  };

  const option = {
    tooltip: {
      trigger: 'axis',
      backgroundColor: chartTheme.tooltipBackground,
      borderColor: chartTheme.tooltipBorder,
      textStyle: { color: chartTheme.tooltipText },
      formatter: (params: { name: string; value: number }[]) => {
        const item = params[0];
        return `${item.name}<br/>营收: $${formatValue(item.value)}`;
      },
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '3%',
      top: '15%',
      containLabel: true,
    },
    xAxis: {
      type: 'category',
      data: data.map((d) => d.period || d.name || ''),
      axisLabel: {
        fontSize: 10,
        color: chartTheme.textSecondary,
      },
      axisLine: { lineStyle: { color: chartTheme.border } },
    },
    yAxis: {
      type: 'value',
      axisLabel: {
        fontSize: 10,
        color: chartTheme.textSecondary,
        formatter: (value: number) => `$${formatValue(value)}`,
      },
      splitLine: { lineStyle: { color: chartTheme.grid } },
    },
    series: [
      {
        type: 'bar',
        data: data.map((d) => d.value || 0),
        itemStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: chartTheme.primary },
              { offset: 1, color: chartTheme.primarySoft },
            ],
          },
          borderRadius: [4, 4, 0, 0],
        },
        barWidth: '60%',
      },
    ],
  };

  return (
    <div className="bg-fin-card border border-fin-border rounded-xl p-4">
      <h3 className="text-sm font-semibold text-fin-text mb-3">{title}</h3>
      <ReactECharts option={option} style={{ height: '200px' }} />
    </div>
  );
}

export default RevenueTrendCard;
