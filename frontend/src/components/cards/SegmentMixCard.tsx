import ReactECharts from 'echarts-for-react';
import { useChartTheme } from '../../hooks/useChartTheme';
import type { ChartPoint } from '../../types/dashboard';

interface SegmentMixCardProps {
  data: ChartPoint[];
  loading?: boolean;
  title?: string;
}

const buildColors = (primary: string, success: string, warning: string, danger: string) => [
  primary,
  success,
  warning,
  danger,
  '#8b5cf6',
  '#06b6d4',
  '#ec4899',
];

export function SegmentMixCard({ data, loading, title = '收入结构' }: SegmentMixCardProps) {
  const chartTheme = useChartTheme();

  if (loading) {
    return (
      <div className="bg-fin-card border border-fin-border rounded-xl p-4 h-64">
        <div className="h-4 bg-fin-border rounded w-24 mb-4" />
        <div className="h-48 bg-fin-border rounded-full mx-auto w-48 animate-pulse" />
      </div>
    );
  }

  if (!data || data.length === 0) {
    return (
      <div className="bg-fin-card border border-fin-border rounded-xl p-4 h-64 flex items-center justify-center text-fin-muted text-sm">
        暂无分部数据
      </div>
    );
  }

  const colors = buildColors(chartTheme.primary, chartTheme.success, chartTheme.warning, chartTheme.danger);

  const option = {
    tooltip: {
      trigger: 'item',
      backgroundColor: chartTheme.tooltipBackground,
      borderColor: chartTheme.tooltipBorder,
      textStyle: { color: chartTheme.tooltipText },
      formatter: '{b}: {c} ({d}%)',
    },
    legend: {
      orient: 'vertical',
      right: '5%',
      top: 'center',
      textStyle: {
        fontSize: 10,
        color: chartTheme.textSecondary,
      },
    },
    series: [
      {
        type: 'pie',
        radius: ['40%', '70%'],
        center: ['35%', '50%'],
        avoidLabelOverlap: false,
        itemStyle: {
          borderRadius: 6,
          borderColor: chartTheme.isDark ? chartTheme.border : '#ffffff',
          borderWidth: 2,
        },
        label: {
          show: false,
        },
        emphasis: {
          label: {
            show: true,
            fontSize: 12,
            fontWeight: 'bold',
            color: chartTheme.text,
          },
        },
        labelLine: {
          show: false,
        },
        data: data.map((item, idx) => ({
          name: item.name || `Segment ${idx + 1}`,
          value: item.value || 0,
          itemStyle: { color: colors[idx % colors.length] },
        })),
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

export default SegmentMixCard;
