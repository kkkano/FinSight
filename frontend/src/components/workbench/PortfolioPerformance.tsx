/**
 * PortfolioPerformance — Tabular view of per-position P&L with a summary footer.
 *
 * Columns: ticker, current price, day change %, unrealised P&L %, unrealised P&L $,
 * market value. Footer row aggregates totals.
 *
 * Colour convention: gains = emerald / green, losses = red.
 */
import { useMemo, useState } from 'react';
import { ArrowUpDown, TrendingDown, TrendingUp } from 'lucide-react';

import { Skeleton } from '../ui';
import { formatCurrency } from '../../utils/format';
import {
  usePortfolioPerformance,
  type PerformanceRow,
  type PerformanceSummary,
} from '../../hooks/usePortfolioPerformance';
import type { PortfolioSummaryResponse } from '../../api/client';

// --- Props ---

interface PortfolioPerformanceProps {
  data: PortfolioSummaryResponse | null;
  loading: boolean;
}

// --- Sort helpers ---

type SortKey = 'ticker' | 'currentPrice' | 'dayChangePct' | 'unrealizedPnlPct' | 'unrealizedPnl' | 'marketValue';
type SortDir = 'asc' | 'desc';

function comparePrimitive(a: number | null, b: number | null, dir: SortDir): number {
  if (a === null && b === null) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  return dir === 'asc' ? a - b : b - a;
}

function sortRows(rows: PerformanceRow[], key: SortKey, dir: SortDir): PerformanceRow[] {
  return [...rows].sort((a, b) => {
    if (key === 'ticker') {
      return dir === 'asc'
        ? a.ticker.localeCompare(b.ticker)
        : b.ticker.localeCompare(a.ticker);
    }
    return comparePrimitive(a[key], b[key], dir);
  });
}

// --- Formatters ---

function formatPct(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  const sign = value >= 0 ? '+' : '';
  return `${sign}${value.toFixed(2)}%`;
}

function formatPnlCurrency(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  const sign = value >= 0 ? '+' : '';
  return `${sign}${formatCurrency(value)}`;
}

function pnlColor(value: number | null | undefined): string {
  if (value === null || value === undefined || value === 0) return 'text-fin-muted';
  return value > 0 ? 'text-emerald-400' : 'text-red-400';
}

// --- Sub-components ---

function HeaderCell({
  label,
  sortKey,
  activeSortKey,
  activeSortDir,
  onSort,
  align = 'right',
}: {
  label: string;
  sortKey: SortKey;
  activeSortKey: SortKey;
  activeSortDir: SortDir;
  onSort: (key: SortKey) => void;
  align?: 'left' | 'right';
}) {
  const isActive = activeSortKey === sortKey;
  return (
    <th
      className={`px-3 py-2 text-2xs font-medium text-fin-muted whitespace-nowrap cursor-pointer select-none hover:text-fin-text transition-colors ${
        align === 'left' ? 'text-left' : 'text-right'
      }`}
      onClick={() => onSort(sortKey)}
    >
      <span className="inline-flex items-center gap-1">
        {label}
        <ArrowUpDown
          size={10}
          className={isActive ? 'text-fin-primary' : 'opacity-30'}
        />
        {isActive && (
          <span className="text-fin-primary text-[9px]">
            {activeSortDir === 'asc' ? '\u25B2' : '\u25BC'}
          </span>
        )}
      </span>
    </th>
  );
}

function SummaryFooter({ summary }: { summary: PerformanceSummary }) {
  return (
    <tr className="border-t border-fin-border bg-fin-card/80">
      <td className="px-3 py-2.5 text-xs font-semibold text-fin-text">
        {summary.positionCount > 0
          ? `${summary.positionCount} 只持仓`
          : '暂无持仓'}
      </td>
      {/* current price — blank */}
      <td />
      {/* day change % */}
      <td className={`px-3 py-2.5 text-xs font-semibold text-right ${pnlColor(summary.totalDayChangePct)}`}>
        {formatPct(summary.totalDayChangePct)}
      </td>
      {/* unrealised PnL % */}
      <td className={`px-3 py-2.5 text-xs font-semibold text-right ${pnlColor(summary.totalPnlPct)}`}>
        {formatPct(summary.totalPnlPct)}
      </td>
      {/* unrealised PnL $ */}
      <td className={`px-3 py-2.5 text-xs font-semibold text-right ${pnlColor(summary.totalPnl)}`}>
        {formatPnlCurrency(summary.totalPnl)}
      </td>
      {/* total market value */}
      <td className="px-3 py-2.5 text-xs font-semibold text-fin-text text-right">
        {formatCurrency(summary.totalMarketValue)}
      </td>
    </tr>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-8 gap-2">
      <TrendingUp size={28} className="text-fin-muted/40" />
      <div className="text-xs text-fin-muted">暂无持仓数据，请先添加持仓</div>
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div className="space-y-2 p-4">
      {Array.from({ length: 4 }).map((_, i) => (
        <Skeleton key={i} variant="rectangular" className="w-full h-8 rounded" />
      ))}
    </div>
  );
}

// --- Main component ---

export function PortfolioPerformance({ data, loading }: PortfolioPerformanceProps) {
  const { rows, summary, isEmpty } = usePortfolioPerformance(data);

  const [sortKey, setSortKey] = useState<SortKey>('marketValue');
  const [sortDir, setSortDir] = useState<SortDir>('desc');

  const handleSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDir((prev) => (prev === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir('desc');
    }
  };

  const sorted = useMemo(() => sortRows(rows, sortKey, sortDir), [rows, sortKey, sortDir]);

  return (
    <div className="bg-fin-card border border-fin-border rounded-xl overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-fin-border">
        <div className="flex items-center gap-2">
          <TrendingUp size={14} className="text-fin-primary" />
          <span className="text-xs font-semibold text-fin-text">持仓收益追踪</span>
        </div>
        {!isEmpty && (
          <div className="flex items-center gap-3 text-2xs text-fin-muted">
            <span>
              总收益：
              <span className={`font-semibold ${pnlColor(summary.totalPnl)}`}>
                {formatPnlCurrency(summary.totalPnl)}
              </span>
            </span>
            <span>
              今日：
              <span className={`font-semibold ${pnlColor(summary.totalDayChange)}`}>
                {summary.totalDayChange >= 0 ? (
                  <TrendingUp size={10} className="inline -mt-0.5 mr-0.5" />
                ) : (
                  <TrendingDown size={10} className="inline -mt-0.5 mr-0.5" />
                )}
                {formatPnlCurrency(summary.totalDayChange)}
              </span>
            </span>
          </div>
        )}
      </div>

      {/* Body */}
      {loading && <LoadingSkeleton />}

      {!loading && isEmpty && <EmptyState />}

      {!loading && !isEmpty && (
        <div className="overflow-x-auto scrollbar-hide">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-fin-border/60">
                <HeaderCell label="股票代码" sortKey="ticker" activeSortKey={sortKey} activeSortDir={sortDir} onSort={handleSort} align="left" />
                <HeaderCell label="当前价格" sortKey="currentPrice" activeSortKey={sortKey} activeSortDir={sortDir} onSort={handleSort} />
                <HeaderCell label="日涨跌幅" sortKey="dayChangePct" activeSortKey={sortKey} activeSortDir={sortDir} onSort={handleSort} />
                <HeaderCell label="持仓收益率" sortKey="unrealizedPnlPct" activeSortKey={sortKey} activeSortDir={sortDir} onSort={handleSort} />
                <HeaderCell label="持仓收益额" sortKey="unrealizedPnl" activeSortKey={sortKey} activeSortDir={sortDir} onSort={handleSort} />
                <HeaderCell label="市值" sortKey="marketValue" activeSortKey={sortKey} activeSortDir={sortDir} onSort={handleSort} />
              </tr>
            </thead>
            <tbody>
              {sorted.map((row) => (
                <tr
                  key={row.ticker}
                  className="border-b border-fin-border/30 hover:bg-fin-hover/40 transition-colors"
                >
                  <td className="px-3 py-2 text-xs font-medium text-fin-text whitespace-nowrap">
                    {row.ticker}
                    <span className="ml-1.5 text-2xs text-fin-muted">
                      x{row.shares}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-xs text-fin-text text-right tabular-nums">
                    {row.currentPrice !== null ? `$${row.currentPrice.toFixed(2)}` : '--'}
                  </td>
                  <td className={`px-3 py-2 text-xs text-right tabular-nums ${pnlColor(row.dayChangePct)}`}>
                    {formatPct(row.dayChangePct)}
                  </td>
                  <td className={`px-3 py-2 text-xs text-right tabular-nums font-medium ${pnlColor(row.unrealizedPnlPct)}`}>
                    {formatPct(row.unrealizedPnlPct)}
                  </td>
                  <td className={`px-3 py-2 text-xs text-right tabular-nums ${pnlColor(row.unrealizedPnl)}`}>
                    {formatPnlCurrency(row.unrealizedPnl)}
                  </td>
                  <td className="px-3 py-2 text-xs text-fin-text text-right tabular-nums">
                    {formatCurrency(row.marketValue)}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <SummaryFooter summary={summary} />
            </tfoot>
          </table>
        </div>
      )}
    </div>
  );
}

export default PortfolioPerformance;
