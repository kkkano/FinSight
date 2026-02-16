import ReactECharts from 'echarts-for-react';
import { useChartTheme } from '../../hooks/useChartTheme';
import type { ChartPoint } from '../../types/dashboard';

interface SectorWeightsCardProps {
  data: ChartPoint[];
  loading?: boolean;
  title?: string;
}

const buildSectorColors = (primary: string, success: string, warning: string, danger: string): Record<string, string> => ({
  IT: primary,
  'Health Care': success,
  Financials: warning,
  'Consumer Disc.': danger,
  Communication: '#8b5cf6',
  Industrials: '#06b6d4',
  Energy: '#f97316',
  Materials: '#84cc16',
  Utilities: '#ec4899',
  'Real Estate': '#14b8a6',
  Other: '#6b7280',
});

export function SectorWeightsCard({ data, loading, title = '行业权重' }: SectorWeightsCardProps) {
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
        暂无行业数据
      </div>
    );
  }

  const sectorColors = buildSectorColors(chartTheme.primary, chartTheme.success, chartTheme.warning, chartTheme.danger);

  const option = {
    tooltip: {
      trigger: 'item',
      backgroundColor: chartTheme.tooltipBackground,
      borderColor: chartTheme.tooltipBorder,
      textStyle: { color: chartTheme.tooltipText },
      formatter: (params: { name: string; value: number }) =>
        `${params.name}: ${(params.value * 100).toFixed(1)}%`,
    },
    legend: {
      orient: 'vertical',
      right: '2%',
      top: 'center',
      textStyle: {
        fontSize: 10,
        color: chartTheme.textSecondary,
      },
      formatter: (name: string) => {
        const item = data.find((row) => row.name === name);
        const pct = item?.value ? (item.value * 100).toFixed(1) : '0';
        return `${name} ${pct}%`;
      },
    },
    series: [
      {
        type: 'pie',
        radius: ['35%', '65%'],
        center: ['30%', '50%'],
        avoidLabelOverlap: false,
        itemStyle: {
          borderRadius: 4,
          borderColor: chartTheme.isDark ? chartTheme.border : '#ffffff',
          borderWidth: 2,
        },
        label: {
          show: false,
        },
        emphasis: {
          label: {
            show: true,
            fontSize: 11,
            fontWeight: 'bold',
            color: chartTheme.text,
          },
        },
        labelLine: {
          show: false,
        },
        data: data.map((row) => ({
          name: row.name || 'Unknown',
          value: row.value || 0,
          itemStyle: {
            color: sectorColors[row.name || ''] || sectorColors.Other,
          },
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

export default SectorWeightsCard;
