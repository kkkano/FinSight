/**
 * ProfitabilityChart - Dual-axis bar + line combo chart for profitability trends.
 *
 * Replaces the old CSS table version with a real ECharts dual-axis chart.
 * Left Y-axis: Revenue/Net Income bars. Right Y-axis: Gross/Net margin lines.
 * Shows up to 8 quarters of data.
 */
import { useMemo } from 'react';
import ReactECharts from 'echarts-for-react';

import { useChartTheme } from '../../../../hooks/useChartTheme';
import type { FinancialStatement } from '../../../../types/dashboard';

// --- Props ---

interface ProfitabilityChartProps {
  financials?: FinancialStatement | null;
}

// --- Helpers ---

/** Format large numbers compactly: $1.2B, $340M, etc. */
const formatLargeNumber = (value: number): string => {
  const abs = Math.abs(value);
  const sign = value < 0 ? '-' : '';
  if (abs >= 1e12) return `${sign}$${(abs / 1e12).toFixed(1)}T`;
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(0)}M`;
  if (abs >= 1e3) return `${sign}$${(abs / 1e3).toFixed(0)}K`;
  return `${sign}$${abs.toFixed(0)}`;
};

interface ChartData {
  periods: string[];
  revenues: number[];
  netIncomes: number[];
  grossMargins: (number | null)[];
  netMargins: (number | null)[];
}

function extractChartData(financials: FinancialStatement | null | undefined): ChartData | null {
  if (!financials) return null;

  const periods = financials.periods ?? [];
  const revenue = financials.revenue ?? [];
  const grossProfit = financials.gross_profit ?? [];
  const netIncome = financials.net_income ?? [];

  if (periods.length === 0) return null;

  // Take last 8 periods
  const start = Math.max(0, periods.length - 8);

  const slicedPeriods: string[] = [];
  const revenues: number[] = [];
  const netIncomes: number[] = [];
  const grossMargins: (number | null)[] = [];
  const netMargins: (number | null)[] = [];

  for (let i = start; i < periods.length; i++) {
    slicedPeriods.push(periods[i]);
    const rev = revenue[i] ?? 0;
    const ni = netIncome[i] ?? 0;
    revenues.push(rev);
    netIncomes.push(ni);

    const gp = grossProfit[i];
    grossMargins.push(rev !== 0 && gp != null ? Math.round((gp / rev) * 1000) / 10 : null);
    netMargins.push(rev !== 0 ? Math.round((ni / rev) * 1000) / 10 : null);
  }

  return { periods: slicedPeriods, revenues, netIncomes, grossMargins, netMargins };
}

// --- Component ---

export function ProfitabilityChart({ financials }: ProfitabilityChartProps) {
  const theme = useChartTheme();

  const option = useMemo(() => {
    const data = extractChartData(financials);
    if (!data) return null;

    return {
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        backgroundColor: theme.tooltipBackground,
        borderColor: theme.tooltipBorder,
        textStyle: { color: theme.tooltipText, fontSize: 11 },
      },
      legend: {
        data: ['营收', '净利润', '毛利率', '净利率'],
        textStyle: { color: theme.muted, fontSize: 10 },
        top: 0,
        itemWidth: 12,
        itemHeight: 8,
      },
      grid: { left: 56, right: 48, top: 32, bottom: 8, containLabel: false },
      xAxis: {
        type: 'category' as const,
        data: data.periods,
        axisLine: { lineStyle: { color: theme.border } },
        axisLabel: { color: theme.muted, fontSize: 9, rotate: 30 },
      },
      yAxis: [
        {
          type: 'value' as const,
          name: '',
          axisLabel: {
            color: theme.muted,
            fontSize: 9,
            formatter: (v: number) => formatLargeNumber(v),
          },
          splitLine: { lineStyle: { color: theme.grid, type: 'dashed' } },
        },
        {
          type: 'value' as const,
          name: '',
          axisLabel: {
            color: theme.muted,
            fontSize: 9,
            formatter: '{value}%',
          },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: '营收',
          type: 'bar',
          data: data.revenues,
          barMaxWidth: 20,
          itemStyle: { color: theme.primary, borderRadius: [2, 2, 0, 0] },
        },
        {
          name: '净利润',
          type: 'bar',
          data: data.netIncomes,
          barMaxWidth: 20,
          itemStyle: { color: theme.success, borderRadius: [2, 2, 0, 0] },
        },
        {
          name: '毛利率',
          type: 'line',
          yAxisIndex: 1,
          data: data.grossMargins,
          smooth: true,
          showSymbol: true,
          symbolSize: 4,
          lineStyle: { color: theme.warning, width: 2 },
          itemStyle: { color: theme.warning },
        },
        {
          name: '净利率',
          type: 'line',
          yAxisIndex: 1,
          data: data.netMargins,
          smooth: true,
          showSymbol: true,
          symbolSize: 4,
          lineStyle: { color: theme.danger, width: 2, type: 'dashed' },
          itemStyle: { color: theme.danger },
        },
      ],
    };
  }, [financials, theme]);

  if (!option) {
    return (
      <div className="p-4 bg-fin-card rounded-xl border border-fin-border">
        <div className="text-xs font-medium text-fin-muted mb-3">盈利能力趋势</div>
        <div className="text-sm text-fin-muted">--</div>
      </div>
    );
  }

  return (
    <div className="p-4 bg-fin-card rounded-xl border border-fin-border">
      <div className="text-xs font-medium text-fin-muted mb-2">盈利能力趋势</div>
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

export default ProfitabilityChart;
