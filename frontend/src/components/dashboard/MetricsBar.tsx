/**
 * MetricsBar - Horizontal key-indicator strip for the v2 dashboard.
 *
 * Shows 7 valuation metrics in a compact row:
 * Market Cap / PE / PB / EPS / Dividend Yield / 52-Week Range / Beta
 *
 * Gracefully degrades to "--" when data is null or missing.
 */
import type { ValuationData, SnapshotData } from '../../types/dashboard';
import { currencySymbolForTicker, formatMarketCapForMarket } from '../../utils/format';

// --- Props ---

interface MetricsBarProps {
  valuation?: ValuationData | null;
  snapshot?: SnapshotData | null;
  ticker?: string | null;
  loading?: boolean;
}

// --- Helpers ---

/** Format a ratio (PE, PB, etc.) to 1 decimal */
const fmtRatio = (v: number | null | undefined): string => {
  if (v === null || v === undefined) return '--';
  return v.toFixed(1);
};

/** Format a dividend yield that may arrive as ratio (0.0036) or percent points (0.36). */
// eslint-disable-next-line react-refresh/only-export-components
export const formatDividendYield = (v: number | null | undefined): string => {
  if (v === null || v === undefined) return '--';
  if (!Number.isFinite(v)) return '--';
  const normalized = Math.abs(v) >= 0.2 ? v : v * 100;
  return `${normalized.toFixed(2)}%`;
};

/** Format a price (52-week range) */
const fmtPrice = (v: number | null | undefined): string => {
  if (v === null || v === undefined) return '--';
  return v.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
};

// --- Metric Definition ---

interface MetricDef {
  label: string;
  value: string;
}

function buildMetrics(
  valuation: ValuationData | null | undefined,
  snapshot: SnapshotData | null | undefined,
  ticker: string | null | undefined,
): MetricDef[] {
  const v = valuation ?? {};
  const s = snapshot ?? {};

  // 市场感知币种前缀：A股 ¥ / 港股 HK$ / 其余 $
  const cur = currencySymbolForTicker(ticker);

  const w52Low = fmtPrice(v.week52_low);
  const w52High = fmtPrice(v.week52_high);
  // 范围只在最前面加一次币种前缀，避免 "¥1 - ¥2" 冗余
  const rangeStr =
    w52Low === '--' && w52High === '--' ? '--' : `${cur}${w52Low} - ${w52High}`;

  return [
    { label: '总市值', value: formatMarketCapForMarket(v.market_cap, ticker) },
    { label: 'P/E', value: fmtRatio(v.trailing_pe) },
    { label: 'P/B', value: fmtRatio(v.price_to_book) },
    { label: 'EPS', value: s.eps !== null && s.eps !== undefined ? `${cur}${s.eps.toFixed(2)}` : '--' },
    { label: '股息率', value: formatDividendYield(v.dividend_yield) },
    { label: '52周范围', value: rangeStr },
    { label: 'Beta', value: fmtRatio(v.beta) },
  ];
}

// --- Component ---

export function MetricsBar({ valuation, snapshot, ticker, loading }: MetricsBarProps) {
  if (loading) {
    return (
      <div className="flex items-stretch gap-0 border-b border-fin-border bg-fin-card overflow-x-auto scrollbar-hide">
        {Array.from({ length: 7 }).map((_, i) => (
          <div
            key={i}
            className="flex-1 min-w-[100px] px-4 py-2.5 border-r border-fin-border last:border-r-0"
          >
            <div className="h-3 w-12 bg-fin-border rounded animate-pulse mb-1.5" />
            <div className="h-5 w-16 bg-fin-border rounded animate-pulse" />
          </div>
        ))}
      </div>
    );
  }

  const metrics = buildMetrics(valuation, snapshot, ticker);

  return (
    <div className="flex items-stretch gap-0 border-b border-fin-border bg-fin-card overflow-x-auto scrollbar-hide">
      {metrics.map((m) => (
        <div
          key={m.label}
          className="flex-1 min-w-[100px] px-4 py-2.5 border-r border-fin-border last:border-r-0"
        >
          <div className="text-2xs text-fin-muted whitespace-nowrap">{m.label}</div>
          <div className="text-sm font-semibold text-fin-text tabular-nums whitespace-nowrap mt-0.5">
            {m.value}
          </div>
        </div>
      ))}
    </div>
  );
}

export default MetricsBar;
