/**
 * BalanceSheetSummary - Key balance sheet items display.
 *
 * Shows: Total Assets / Total Liabilities / Equity / D/E Ratio
 * Computed from the latest period in financials data.
 */
import { useMemo } from 'react';

import type { FinancialStatement } from '../../../../types/dashboard';
import { DashboardSourceBadge } from '../../DashboardSourceBadge';
import { formatMoney } from '../../../../utils/format';

// --- Props ---

interface BalanceSheetSummaryProps {
  financials?: FinancialStatement | null;
}

// --- Helpers ---

const fmtRatio = (v: number | null | undefined): string => {
  if (v === null || v === undefined) return '--';
  return v.toFixed(2);
};

// --- Types ---

interface BalanceItem {
  label: string;
  value: string;
  subtext?: string;
}

function buildItems(financials: FinancialStatement | null | undefined): BalanceItem[] {
  if (!financials) {
    return [
      { label: '总资产', value: '--' },
      { label: '总负债', value: '--' },
      { label: '股东权益', value: '--' },
      { label: '负债/权益比', value: '--' },
    ];
  }

  const summary = financials.balance_summary;
  const money = (value: number | null | undefined) => formatMoney(value, financials.currency, true);

  return [
    { label: '总资产', value: formatMoney(summary?.total_assets, financials.metric_currencies?.total_assets ?? financials.currency, true), subtext: summary?.period ?? undefined },
    { label: '总负债', value: formatMoney(summary?.total_liabilities, financials.metric_currencies?.total_liabilities ?? financials.currency, true) },
    { label: '股东权益', value: money(summary?.equity) },
    { label: '负债/权益比', value: fmtRatio(summary?.de_ratio) },
  ];
}

// --- Component ---

export function BalanceSheetSummary({ financials }: BalanceSheetSummaryProps) {
  const items = useMemo(() => buildItems(financials), [financials]);

  return (
    <div className="p-4 bg-fin-card rounded-lg border border-fin-border">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="text-xs font-medium text-fin-muted">资产负债概要</div>
        <DashboardSourceBadge metaKey="financials" />
      </div>

      <div className="grid grid-cols-2 gap-4">
        {items.map((item) => (
          <div key={item.label} className="flex flex-col">
            <span className="text-2xs text-fin-muted">{item.label}</span>
            <span className="text-sm font-semibold text-fin-text tabular-nums mt-0.5">
              {item.value}
            </span>
            {item.subtext && (
              <span className="text-2xs text-fin-muted mt-0.5">{item.subtext}</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export default BalanceSheetSummary;
