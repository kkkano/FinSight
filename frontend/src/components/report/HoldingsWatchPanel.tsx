import React from 'react';
import { BriefcaseBusiness, ChevronDown } from 'lucide-react';

import type { Form4TransactionRow, HoldingsInsight, InstitutionalHoldingRow } from '../../types/index';

export interface HoldingsWatchPanelProps {
  holdings?: HoldingsInsight | null;
}

const DEFAULT_13F_NOTE = 'SEC Form 13F is due within 45 days after each calendar quarter end.';
const DEFAULT_FORM4_NOTE = 'In most cases, Form 4 is filed within two business days following the transaction date.';

const formatNumber = (value: number | null | undefined): string => {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'N/A';
  return value.toLocaleString('en-US', { maximumFractionDigits: 2 });
};

const formatPrice = (value: number | null | undefined): string => {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'N/A';
  return `$${value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
};

const formatHoldingValue = (value: number | null | undefined): string => {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'N/A';
  return `$${value.toLocaleString('en-US')}k`;
};

const ownerName = (row: Form4TransactionRow): string =>
  row.owner_name || row.reporting_owner_name || 'Unknown owner';

const holdingName = (row: InstitutionalHoldingRow): string =>
  row.issuer_name || row.ticker || row.cusip || 'Unknown issuer';

export const HoldingsWatchPanel: React.FC<HoldingsWatchPanelProps> = ({ holdings }) => {
  const institutionalRows = holdings?.holdings || [];
  const transactionRows = holdings?.transactions || [];
  const form13fNote = holdings?.regulatory_notes?.form_13f_due || DEFAULT_13F_NOTE;
  const form4Note = holdings?.regulatory_notes?.form_4_due || DEFAULT_FORM4_NOTE;

  return (
    <details className="group rounded-xl border border-fin-border bg-fin-card overflow-hidden" open>
      <summary className="px-4 py-3 cursor-pointer hover:bg-fin-hover transition-colors flex items-center gap-2">
        <ChevronDown size={16} className="text-fin-muted group-open:rotate-180 transition-transform" />
        <BriefcaseBusiness size={15} className="text-fin-primary" />
        <span className="text-sm font-semibold text-fin-text">持仓披露观察</span>
        <span className="ml-auto text-2xs text-fin-muted">
          {holdings ? `${institutionalRows.length} 13F · ${transactionRows.length} Form 4` : 'missing'}
        </span>
      </summary>

      {!holdings ? (
        <div className="px-4 pb-4">
          <div className="rounded-lg border border-dashed border-fin-border bg-fin-bg-secondary px-3 py-3 text-xs text-fin-muted">
            暂无持仓披露结果
          </div>
        </div>
      ) : (
        <div className="px-4 pb-4 space-y-3">
          <div className="grid gap-2 md:grid-cols-2">
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-800 dark:border-amber-900/60 dark:bg-amber-900/20 dark:text-amber-200">
              <span className="font-semibold">13F delay note: </span>
              {form13fNote}
            </div>
            <div className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-xs leading-relaxed text-blue-800 dark:border-blue-900/60 dark:bg-blue-900/20 dark:text-blue-200">
              <span className="font-semibold">Form 4 note: </span>
              {form4Note}
            </div>
          </div>

          {institutionalRows.length > 0 && (
            <div className="overflow-hidden rounded-lg border border-fin-border bg-fin-bg">
              <div className="grid grid-cols-[minmax(0,1fr)_72px_96px_96px] gap-2 border-b border-fin-border bg-fin-bg-secondary px-3 py-2 text-2xs font-medium uppercase tracking-wide text-fin-muted">
                <span>13F issuer</span>
                <span>Ticker</span>
                <span>Value</span>
                <span>Shares</span>
              </div>
              <div className="divide-y divide-fin-border/70">
                {institutionalRows.slice(0, 6).map((row, index) => (
                  <div
                    key={`${row.cusip || row.ticker || index}`}
                    className="grid grid-cols-[minmax(0,1fr)_72px_96px_96px] gap-2 px-3 py-2 text-xs text-fin-text"
                  >
                    <span className="truncate font-medium">{holdingName(row)}</span>
                    <span className="truncate text-fin-text-secondary">{row.ticker || 'N/A'}</span>
                    <span className="tabular-nums text-fin-text-secondary">{formatHoldingValue(row.value_usd_thousands)}</span>
                    <span className="tabular-nums text-fin-text-secondary">{formatNumber(row.shares)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="overflow-hidden rounded-lg border border-fin-border bg-fin-bg">
            <div className="grid grid-cols-[minmax(0,1fr)_82px_48px_48px_74px_82px] gap-2 border-b border-fin-border bg-fin-bg-secondary px-3 py-2 text-2xs font-medium uppercase tracking-wide text-fin-muted">
              <span>Form 4 owner</span>
              <span>Date</span>
              <span>Code</span>
              <span>A/D</span>
              <span>Shares</span>
              <span>Price</span>
            </div>
            {transactionRows.length > 0 ? (
              <div className="divide-y divide-fin-border/70">
                {transactionRows.slice(0, 8).map((row, index) => (
                  <div
                    key={`${ownerName(row)}-${row.transaction_date || index}-${row.transaction_code || ''}`}
                    className="grid grid-cols-[minmax(0,1fr)_82px_48px_48px_74px_82px] gap-2 px-3 py-2 text-xs text-fin-text"
                  >
                    <span className="min-w-0">
                      <span className="block truncate font-medium">{ownerName(row)}</span>
                      <span className="block truncate text-2xs text-fin-muted">
                        {row.security_title || row.security_type || 'security'}
                      </span>
                    </span>
                    <span className="truncate text-fin-text-secondary">{row.transaction_date || row.filing_date || 'N/A'}</span>
                    <span className="font-semibold text-fin-text">{row.transaction_code || 'N/A'}</span>
                    <span className="text-fin-text-secondary">{row.acquired_disposed || 'N/A'}</span>
                    <span className="tabular-nums text-fin-text-secondary">{formatNumber(row.shares)}</span>
                    <span className="tabular-nums text-fin-text-secondary">{formatPrice(row.price_per_share)}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="px-3 py-3 text-xs text-fin-muted">暂无 Form 4 transaction rows</div>
            )}
          </div>
        </div>
      )}
    </details>
  );
};
