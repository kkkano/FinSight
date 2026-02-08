/**
 * Revenue Trend Card - 营收趋势柱状图
 *
 * 使用 ECharts 展示季度营收趋势
 */
import ReactECharts from 'echarts-for-react';
import type { ChartPoint } from '../../types/dashboard';

interface RevenueTrendCardProps {
  data: ChartPoint[];
  loading?: boolean;
  title?: string;
}

export function RevenueTrendCard({
  data,
  loading,
  title = '营收趋势',
}: RevenueTrendCardProps) {
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

  // 格式化数值
  const formatValue = (value: number) => {
    if (value >= 1e9) return `${(value / 1e9).toFixed(1)}B`;
    if (value >= 1e6) return `${(value / 1e6).toFixed(1)}M`;
    return value.toLocaleString();
  };

  const option = {
    tooltip: {
      trigger: 'axis',
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
        color: '#888',
      },
      axisLine: { lineStyle: { color: '#e5e7eb' } },
    },
    yAxis: {
      type: 'value',
      axisLabel: {
        fontSize: 10,
        color: '#888',
        formatter: (value: number) => `$${formatValue(value)}`,
      },
      splitLine: { lineStyle: { color: '#f0f0f0' } },
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
              { offset: 0, color: '#3b82f6' },
              { offset: 1, color: '#60a5fa' },
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
