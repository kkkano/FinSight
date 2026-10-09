/**
 * ProfitabilityChart - Dual-axis bar + line combo chart for profitability trends.
 *
 * Replaces the old CSS table version with a real ECharts dual-axis chart.
 * Left Y-axis: Revenue/Net Income bars. Right Y-axis: Gross/Net margin lines.
 * Shows up to 8 quarters of data.
 */
import { useMemo } from 'react';
import ReactECharts from '../../../charts/EChart';

import { useChartTheme } from '../../../../hooks/useChartTheme';
import type { FinancialStatement } from '../../../../types/dashboard';
import { DashboardSourceBadge } from '../../DashboardSourceBadge';
import { formatMoney } from '../../../../utils/format';

// --- Props ---

interface ProfitabilityChartProps {
  financials?: FinancialStatement | null;
}

// --- Helpers ---

interface ChartData {
  periods: string[];
  revenues: (number | null)[];
  netIncomes: (number | null)[];
  grossMargins: (number | null)[];
  netMargins: (number | null)[];
}

function extractChartData(financials: FinancialStatement | null | undefined): ChartData | null {
  if (!financials) return null;

  const periods = financials.periods ?? [];
  const revenue = financials.revenue ?? [];
  const netIncome = financials.net_income ?? [];

  if (periods.length === 0) return null;

  const slicedPeriods: string[] = [];
  const revenues: (number | null)[] = [];
  const netIncomes: (number | null)[] = [];
  const grossMargins: (number | null)[] = [];
  const netMargins: (number | null)[] = [];

  const indices = periods.map((_, idx) => idx)
    .sort((a, b) => (financials.period_ends?.[b] ?? periods[b]).localeCompare(financials.period_ends?.[a] ?? periods[a]))
    .slice(0, 8).reverse();
  for (const i of indices) {
    slicedPeriods.push(periods[i]);
    const rev = revenue[i] ?? null;
    const ni = netIncome[i] ?? null;
    revenues.push(rev);
    netIncomes.push(ni);

    grossMargins.push(financials.gross_margin?.[i] ?? null);
    netMargins.push(financials.net_margin?.[i] ?? null);
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
            formatter: (v: number) => formatMoney(v, financials?.currency, true),
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
      <div className="p-4 bg-fin-card rounded-lg border border-fin-border">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div className="text-xs font-medium text-fin-muted">盈利能力趋势</div>
          <DashboardSourceBadge metaKey="financials" />
        </div>
        <div className="text-sm text-fin-muted">--</div>
      </div>
    );
  }

  return (
    <div className="p-4 bg-fin-card rounded-lg border border-fin-border">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="text-xs font-medium text-fin-muted">盈利能力趋势</div>
        <DashboardSourceBadge metaKey="financials" />
      </div>
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
