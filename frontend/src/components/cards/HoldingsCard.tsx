import ReactECharts from 'echarts-for-react';
import { useChartTheme } from '../../hooks/useChartTheme';
import type { ChartPoint } from '../../types/dashboard';

interface HoldingsCardProps {
  data: ChartPoint[];
  loading?: boolean;
  title?: string;
}

const buildPalette = (primary: string, success: string, warning: string, danger: string) => [
  primary,
  success,
  warning,
  danger,
  '#8b5cf6',
  '#06b6d4',
  '#ec4899',
  '#84cc16',
  '#f97316',
  '#14b8a6',
];

export function HoldingsCard({ data, loading, title = '持仓明细' }: HoldingsCardProps) {
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
        暂无持仓数据
      </div>
    );
  }

  const colors = buildPalette(chartTheme.primary, chartTheme.success, chartTheme.warning, chartTheme.danger);

  const sortedData = [...data]
    .sort((a, b) => (b.weight || 0) - (a.weight || 0))
    .slice(0, 10);

  const option = {
    tooltip: {
      trigger: 'item',
      backgroundColor: chartTheme.tooltipBackground,
      borderColor: chartTheme.tooltipBorder,
      textStyle: { color: chartTheme.tooltipText },
      formatter: (params: { name: string; value: number }) =>
        `${params.name}: ${(params.value * 100).toFixed(2)}%`,
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
        const item = sortedData.find((row) => row.symbol === name);
        const pct = item?.weight ? (item.weight * 100).toFixed(1) : '0';
        return `${name} ${pct}%`;
      },
    },
    series: [
      {
        type: 'pie',
        radius: ['30%', '60%'],
        center: ['30%', '50%'],
        roseType: 'radius',
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
        data: sortedData.map((row, idx) => ({
          name: row.symbol || `#${idx + 1}`,
          value: row.weight || 0,
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

export default HoldingsCard;
