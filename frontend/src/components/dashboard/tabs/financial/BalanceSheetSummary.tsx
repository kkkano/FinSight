/**
 * BalanceSheetSummary - Key balance sheet items display.
 *
 * Shows: Total Assets / Total Liabilities / Equity / D/E Ratio
 * Computed from the latest period in financials data.
 */
import { useMemo } from 'react';

import type { FinancialStatement } from '../../../../types/dashboard';

// --- Props ---

interface BalanceSheetSummaryProps {
  financials?: FinancialStatement | null;
}

// --- Helpers ---

const fmtNum = (v: number | null | undefined): string => {
  if (v === null || v === undefined) return '--';
  if (Math.abs(v) >= 1e12) return `$${(v / 1e12).toFixed(1)}T`;
  if (Math.abs(v) >= 1e9) return `$${(v / 1e9).toFixed(1)}B`;
  if (Math.abs(v) >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
  return `$${v.toLocaleString()}`;
};

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

const pickLatestAvailable = (
  periods: string[] | undefined,
  series: Array<number | null> | undefined,
): { value: number | null; period?: string } => {
  if (!Array.isArray(series) || series.length === 0) return { value: null };
  for (let idx = 0; idx < series.length; idx += 1) {
    const value = series[idx];
    if (value != null) {
      return { value, period: periods?.[idx] };
    }
  }
  return { value: null };
};

function buildItems(financials: FinancialStatement | null | undefined): BalanceItem[] {
  if (!financials) {
    return [
      { label: '总资产', value: '--' },
      { label: '总负债', value: '--' },
      { label: '股东权益', value: '--' },
      { label: '负债/权益比', value: '--' },
    ];
  }

  const latestAssets = pickLatestAvailable(financials.periods, financials.total_assets);
  const latestLiabilities = pickLatestAvailable(financials.periods, financials.total_liabilities);
  const totalAssets = latestAssets.value;
  const totalLiabilities = latestLiabilities.value;
  const period = latestAssets.period ?? latestLiabilities.period ?? '';

  // Compute equity = assets - liabilities
  let equity: number | null = null;
  if (totalAssets != null && totalLiabilities != null) {
    equity = totalAssets - totalLiabilities;
  }

  // D/E ratio
  let deRatio: number | null = null;
  if (totalLiabilities != null && equity != null && equity !== 0) {
    deRatio = totalLiabilities / equity;
  }

  return [
    { label: '总资产', value: fmtNum(totalAssets), subtext: period },
    { label: '总负债', value: fmtNum(totalLiabilities) },
    { label: '股东权益', value: fmtNum(equity) },
    { label: '负债/权益比', value: fmtRatio(deRatio) },
  ];
}

// --- Component ---

export function BalanceSheetSummary({ financials }: BalanceSheetSummaryProps) {
  const items = useMemo(() => buildItems(financials), [financials]);

  return (
    <div className="p-4 bg-fin-card rounded-xl border border-fin-border">
      <div className="text-xs font-medium text-fin-muted mb-3">资产负债概要</div>

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
