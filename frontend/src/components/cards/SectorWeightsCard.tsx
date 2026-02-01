/**
 * Sector Weights Card - 行业权重饼图
 *
 * 用于展示指数/ETF 的行业分布
 */
import ReactECharts from 'echarts-for-react';
import type { ChartPoint } from '../../types/dashboard';

interface SectorWeightsCardProps {
  data: ChartPoint[];
  loading?: boolean;
  title?: string;
}

export function SectorWeightsCard({
  data,
  loading,
  title = '行业权重',
}: SectorWeightsCardProps) {
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

  // 行业颜色映射
  const sectorColors: Record<string, string> = {
    IT: '#3b82f6',
    'Health Care': '#10b981',
    Financials: '#f59e0b',
    'Consumer Disc.': '#ef4444',
    Communication: '#8b5cf6',
    Industrials: '#06b6d4',
    Energy: '#f97316',
    Materials: '#84cc16',
    Utilities: '#ec4899',
    'Real Estate': '#14b8a6',
    Other: '#6b7280',
  };

  const option = {
    tooltip: {
      trigger: 'item',
      formatter: (params: { name: string; value: number; percent: number }) =>
        `${params.name}: ${(params.value * 100).toFixed(1)}%`,
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
        const item = data.find((d) => d.name === name);
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
        labelLine: {
          show: false,
        },
        data: data.map((d) => ({
          name: d.name || 'Unknown',
          value: d.value || 0,
          itemStyle: {
            color: sectorColors[d.name || ''] || '#6b7280',
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
