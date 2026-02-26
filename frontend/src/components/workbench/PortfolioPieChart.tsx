/**
 * PortfolioPieChart - Donut chart showing portfolio position allocation.
 *
 * Displays each position's market value as a percentage of total portfolio.
 * Center label shows total portfolio value.
 */
import { useMemo } from 'react';
import ReactECharts from 'echarts-for-react';

import { useChartTheme } from '../../hooks/useChartTheme';
import { formatCurrency } from '../../utils/format';
import type { PortfolioSummaryPosition } from '../../api/client';

// --- Props ---

interface PortfolioPieChartProps {
  positions: PortfolioSummaryPosition[];
  totalValue: number;
}

// --- Component ---

export function PortfolioPieChart({ positions, totalValue }: PortfolioPieChartProps) {
  const theme = useChartTheme();

  const option = useMemo(() => {
    if (positions.length === 0) return null;

    const sorted = [...positions]
      .sort((a, b) => b.market_value - a.market_value);

    // Show top 8, group rest as "其他"
    const MAX_SLICES = 8;
    const top = sorted.slice(0, MAX_SLICES);
    const rest = sorted.slice(MAX_SLICES);
    const restValue = rest.reduce((sum, p) => sum + p.market_value, 0);

    const pieData = [
      ...top.map((p) => ({
        name: p.ticker,
        value: p.market_value,
      })),
      ...(restValue > 0 ? [{ name: '其他', value: restValue }] : []),
    ];

    const colors = [
      theme.primary,
      theme.success,
      theme.warning,
      theme.danger,
      '#8b5cf6',
      '#06b6d4',
      '#ec4899',
      '#f97316',
      theme.muted,
    ];

    return {
      tooltip: {
        trigger: 'item' as const,
        backgroundColor: theme.tooltipBackground,
        borderColor: theme.tooltipBorder,
        textStyle: { color: theme.tooltipText, fontSize: 11 },
        formatter: (params: { name: string; value: number; percent: number }) =>
          `<div style="font-size:11px"><b>${params.name}</b><br/>` +
          `${formatCurrency(params.value)} (${params.percent.toFixed(1)}%)</div>`,
      },
      series: [{
        type: 'pie',
        radius: ['45%', '72%'],
        center: ['50%', '50%'],
        data: pieData,
        label: {
          color: theme.muted,
          fontSize: 10,
          formatter: '{b}\n{d}%',
        },
        labelLine: {
          lineStyle: { color: theme.border },
        },
        itemStyle: {
          borderColor: theme.isDark ? '#1e2028' : '#ffffff',
          borderWidth: 2,
        },
        color: colors,
        emphasis: {
          itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.3)' },
        },
      }],
      graphic: [{
        type: 'text',
        left: 'center',
        top: 'center',
        style: {
          text: formatCurrency(totalValue),
          fontSize: 14,
          fontWeight: 'bold',
          fill: theme.text,
          textAlign: 'center',
        },
      }],
    };
  }, [positions, totalValue, theme]);

  if (!option) {
    return null;
  }

  return (
    <div className="p-4 bg-fin-card rounded-xl border border-fin-border">
      <div className="text-xs font-medium text-fin-muted mb-2">持仓分布</div>
      <ReactECharts
        option={option}
        style={{ width: '100%', height: 260 }}
        opts={{ renderer: 'svg' }}
        notMerge
        lazyUpdate
      />
    </div>
  );
}

export default PortfolioPieChart;
