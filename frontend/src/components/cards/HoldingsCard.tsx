/**
 * Holdings Card - ETF 持仓饼图
 *
 * 用于展示 ETF/Portfolio 的持仓分布
 */
import ReactECharts from 'echarts-for-react';
import type { ChartPoint } from '../../types/dashboard';

interface HoldingsCardProps {
  data: ChartPoint[];
  loading?: boolean;
  title?: string;
}

export function HoldingsCard({
  data,
  loading,
  title = '持仓明细',
}: HoldingsCardProps) {
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

  // 颜色序列
  const colors = [
    '#3b82f6',
    '#10b981',
    '#f59e0b',
    '#ef4444',
    '#8b5cf6',
    '#06b6d4',
    '#ec4899',
    '#84cc16',
    '#f97316',
    '#14b8a6',
  ];

  // 排序取前 10
  const sortedData = [...data]
    .sort((a, b) => (b.weight || 0) - (a.weight || 0))
    .slice(0, 10);

  const option = {
    tooltip: {
      trigger: 'item',
      formatter: (params: { name: string; value: number }) =>
        `${params.name}: ${(params.value * 100).toFixed(2)}%`,
    },
    legend: {
      orient: 'vertical',
      right: '2%',
      top: 'center',
      textStyle: {
        fontSize: 10,
        color: '#666',
      },
      formatter: (name: string) => {
        const item = sortedData.find((d) => d.symbol === name);
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
          borderColor: '#fff',
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
          },
        },
        data: sortedData.map((d, i) => ({
          name: d.symbol || `#${i + 1}`,
          value: d.weight || 0,
          itemStyle: { color: colors[i % colors.length] },
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
