/**
 * IncomeTable - Quarterly income statement table.
 *
 * Rows: Revenue / Gross Profit / Operating Income / Net Income / EPS
 * Columns: last 8 quarters from financials.periods
 * YoY change highlighting: green up, red down.
 */
import { useMemo } from 'react';

import type { FinancialStatement } from '../../../../types/dashboard';
import { DashboardSourceBadge } from '../../DashboardSourceBadge';
import { formatMoney } from '../../../../utils/format';

// --- Props ---

interface IncomeTableProps {
  financials?: FinancialStatement | null;
}

// --- Helpers ---

function yoyClass(change: number | null | undefined): string {
  if (change == null) return '';
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
    () => (financials?.periods ?? []).slice(0, 8),
    [financials],
  );

  if (!financials || periods.length === 0) {
    return (
      <div className="p-4 bg-fin-card rounded-lg border border-fin-border">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div className="text-xs font-medium text-fin-muted">利润表</div>
          <DashboardSourceBadge metaKey="financials" />
        </div>
        <div className="text-sm text-fin-muted">--</div>
      </div>
    );
  }

  return (
    <div className="p-4 bg-fin-card rounded-lg border border-fin-border overflow-x-auto">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="text-xs font-medium text-fin-muted">利润表{financials.frequency === 'annual' ? ' · 年度' : financials.frequency === 'quarterly' ? ' · 单季' : financials.frequency === 'semiannual' ? ' · 半年' : ''}</div>
        <DashboardSourceBadge metaKey="financials" />
      </div>

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
                  const dataIdx = colIdx;
                  const val = values[dataIdx];
                  const colorClass = yoyClass(financials.yoy?.[row.key]?.[dataIdx]);
                  return (
                    <td
                      key={colIdx}
                      className={`text-right py-2 px-2 tabular-nums whitespace-nowrap ${
                        colorClass || 'text-fin-text'
                      }`}
                    >
                      {formatMoney(val, financials.metric_currencies?.[row.key] ?? financials.currency, row.key !== 'eps')}
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
