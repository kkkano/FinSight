/**
 * IncomeTable - Quarterly income statement table.
 *
 * Rows: Revenue / Gross Profit / Operating Income / Net Income / EPS
 * Columns: last 8 quarters from financials.periods
 * YoY change highlighting: green up, red down.
 */
import { useMemo } from 'react';

import type { FinancialStatement } from '../../../../types/dashboard';

// --- Props ---

interface IncomeTableProps {
  financials?: FinancialStatement | null;
}

// --- Helpers ---

/** Format large numbers into compact representation */
const fmtNum = (v: number | null | undefined): string => {
  if (v === null || v === undefined) return '--';
  if (Math.abs(v) >= 1e9) return `${(v / 1e9).toFixed(1)}B`;
  if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (Math.abs(v) >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return v.toFixed(2);
};

/** Compute YoY change class for a value compared to prior-year quarter (4 periods back) */
function yoyClass(values: (number | null)[], index: number): string {
  if (index < 4) return '';
  const current = values[index];
  const prior = values[index - 4];
  if (current == null || prior == null || prior === 0) return '';
  const change = (current - prior) / Math.abs(prior);
  if (change > 0.05) return 'text-fin-success';
  if (change < -0.05) return 'text-fin-danger';
  return '';
}

// --- Types ---

interface RowDef {
  label: string;
  key: keyof Pick<FinancialStatement, 'revenue' | 'gross_profit' | 'operating_income' | 'net_income' | 'eps'>;
}

const ROWS: RowDef[] = [
  { label: '营业收入', key: 'revenue' },
  { label: '毛利润', key: 'gross_profit' },
  { label: '营业利润', key: 'operating_income' },
  { label: '净利润', key: 'net_income' },
  { label: '每股收益', key: 'eps' },
];

// --- Component ---

export function IncomeTable({ financials }: IncomeTableProps) {
  const periods = useMemo(
    () => (financials?.periods ?? []).slice(-8),
    [financials],
  );

  const startIdx = useMemo(() => {
    const total = financials?.periods?.length ?? 0;
    return Math.max(0, total - 8);
  }, [financials]);

  if (!financials || periods.length === 0) {
    return (
      <div className="p-4 bg-fin-card rounded-xl border border-fin-border">
        <div className="text-xs font-medium text-fin-muted mb-3">利润表</div>
        <div className="text-sm text-fin-muted">--</div>
      </div>
    );
  }

  return (
    <div className="p-4 bg-fin-card rounded-xl border border-fin-border overflow-x-auto">
      <div className="text-xs font-medium text-fin-muted mb-3">利润表</div>

      <table className="w-full text-2xs">
        <thead>
          <tr className="border-b border-fin-border">
            <th className="text-left py-2 pr-4 text-fin-muted font-medium whitespace-nowrap sticky left-0 bg-fin-card">
              指标
            </th>
            {periods.map((p) => (
              <th key={p} className="text-right py-2 px-2 text-fin-muted font-medium whitespace-nowrap">
                {p}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ROWS.map((row) => {
            const values = financials[row.key] ?? [];
            return (
              <tr key={row.key} className="border-b border-fin-border/50 last:border-b-0">
                <td className="py-2 pr-4 text-fin-text font-medium whitespace-nowrap sticky left-0 bg-fin-card">
                  {row.label}
                </td>
                {periods.map((_, colIdx) => {
                  const dataIdx = startIdx + colIdx;
                  const val = values[dataIdx];
                  const colorClass = yoyClass(values, dataIdx);
                  return (
                    <td
                      key={colIdx}
                      className={`text-right py-2 px-2 tabular-nums whitespace-nowrap ${
                        colorClass || 'text-fin-text'
                      }`}
                    >
                      {fmtNum(val)}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default IncomeTable;
