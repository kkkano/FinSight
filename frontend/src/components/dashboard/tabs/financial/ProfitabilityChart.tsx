/**
 * ProfitabilityChart - Profitability trends display (table-based).
 *
 * Shows gross margin + net margin trends across available periods.
 * Uses bar representation since ECharts may not be available.
 */
import { useMemo } from 'react';

import type { FinancialStatement } from '../../../../types/dashboard';

// --- Props ---

interface ProfitabilityChartProps {
  financials?: FinancialStatement | null;
}

// --- Types ---

interface MarginEntry {
  period: string;
  grossMargin: number | null;
  netMargin: number | null;
}

// --- Helpers ---

const fmtPct = (v: number | null): string => {
  if (v === null) return '--';
  return `${(v * 100).toFixed(1)}%`;
};

function computeMargins(financials: FinancialStatement | null | undefined): MarginEntry[] {
  if (!financials) return [];

  const periods = financials.periods ?? [];
  const revenue = financials.revenue ?? [];
  const grossProfit = financials.gross_profit ?? [];
  const netIncome = financials.net_income ?? [];

  // Take last 8 periods
  const start = Math.max(0, periods.length - 8);

  return periods.slice(start).map((period, i) => {
    const idx = start + i;
    const rev = revenue[idx];

    let grossMargin: number | null = null;
    let netMargin: number | null = null;

    if (rev != null && rev !== 0) {
      const gp = grossProfit[idx];
      if (gp != null) grossMargin = gp / rev;

      const ni = netIncome[idx];
      if (ni != null) netMargin = ni / rev;
    }

    return { period, grossMargin, netMargin };
  });
}

// --- Component ---

export function ProfitabilityChart({ financials }: ProfitabilityChartProps) {
  const margins = useMemo(() => computeMargins(financials), [financials]);

  if (margins.length === 0) {
    return (
      <div className="p-4 bg-fin-card rounded-xl border border-fin-border">
        <div className="text-xs font-medium text-fin-muted mb-3">盈利能力趋势</div>
        <div className="text-sm text-fin-muted">--</div>
      </div>
    );
  }

  // Find max margin for bar scaling
  const maxVal = margins.reduce((max, m) => {
    const gm = m.grossMargin ?? 0;
    const nm = m.netMargin ?? 0;
    return Math.max(max, Math.abs(gm), Math.abs(nm));
  }, 0);
  const scale = maxVal > 0 ? maxVal : 1;

  return (
    <div className="p-4 bg-fin-card rounded-xl border border-fin-border overflow-x-auto">
      <div className="text-xs font-medium text-fin-muted mb-3">盈利能力趋势</div>

      {/* Legend */}
      <div className="flex items-center gap-4 mb-3">
        <div className="flex items-center gap-1.5 text-2xs">
          <span className="w-3 h-2 rounded-sm bg-fin-success inline-block" />
          <span className="text-fin-muted">毛利率</span>
        </div>
        <div className="flex items-center gap-1.5 text-2xs">
          <span className="w-3 h-2 rounded-sm bg-fin-primary inline-block" />
          <span className="text-fin-muted">净利率</span>
        </div>
      </div>

      {/* Table with bars */}
      <table className="w-full text-2xs">
        <thead>
          <tr className="border-b border-fin-border">
            <th className="text-left py-1.5 pr-3 text-fin-muted font-medium">期间</th>
            <th className="text-left py-1.5 text-fin-muted font-medium">利润率</th>
            <th className="text-right py-1.5 pl-3 text-fin-muted font-medium">毛利率</th>
            <th className="text-right py-1.5 pl-3 text-fin-muted font-medium">净利率</th>
          </tr>
        </thead>
        <tbody>
          {margins.map((m) => (
            <tr key={m.period} className="border-b border-fin-border/50 last:border-b-0">
              <td className="py-1.5 pr-3 text-fin-text whitespace-nowrap">{m.period}</td>
              <td className="py-1.5 w-40">
                <div className="flex flex-col gap-0.5">
                  <div
                    className="h-1.5 rounded-full bg-fin-success"
                    style={{ width: `${Math.max(0, ((m.grossMargin ?? 0) / scale) * 100)}%` }}
                  />
                  <div
                    className="h-1.5 rounded-full bg-fin-primary"
                    style={{ width: `${Math.max(0, ((m.netMargin ?? 0) / scale) * 100)}%` }}
                  />
                </div>
              </td>
              <td className="text-right py-1.5 pl-3 tabular-nums text-fin-text">{fmtPct(m.grossMargin)}</td>
              <td className="text-right py-1.5 pl-3 tabular-nums text-fin-text">{fmtPct(m.netMargin)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default ProfitabilityChart;
