/**
 * ValuationGrid - 2x3 grid of key valuation metrics.
 *
 * Displays: PE / Forward PE / PB / EV-EBITDA / P/S / Dividend Yield
 * Data sourced from dashboardData.valuation.
 */
import type { ValuationData } from '../../../../types/dashboard';

// --- Props ---

interface ValuationGridProps {
  valuation?: ValuationData | null;
}

// --- Helpers ---

const fmtRatio = (v: number | null | undefined): string => {
  if (v === null || v === undefined) return '--';
  return v.toFixed(2);
};

const fmtPct = (v: number | null | undefined): string => {
  if (v === null || v === undefined) return '--';
  return `${(v * 100).toFixed(2)}%`;
};

// --- Types ---

interface MetricDef {
  label: string;
  value: string;
}

function buildMetrics(valuation: ValuationData | null | undefined): MetricDef[] {
  const v = valuation ?? {};
  return [
    { label: 'P/E (TTM)', value: fmtRatio(v.trailing_pe) },
    { label: 'P/E (Forward)', value: fmtRatio(v.forward_pe) },
    { label: 'P/B', value: fmtRatio(v.price_to_book) },
    { label: 'EV/EBITDA', value: fmtRatio(v.ev_to_ebitda) },
    { label: 'P/S', value: fmtRatio(v.price_to_sales) },
    { label: '股息率', value: fmtPct(v.dividend_yield) },
  ];
}

// --- Component ---

export function ValuationGrid({ valuation }: ValuationGridProps) {
  const metrics = buildMetrics(valuation);

  return (
    <div className="p-4 bg-fin-card rounded-xl border border-fin-border">
      <div className="text-xs font-medium text-fin-muted mb-3">估值指标</div>

      <div className="grid grid-cols-3 gap-3">
        {metrics.map((m) => (
          <div key={m.label} className="flex flex-col">
            <span className="text-2xs text-fin-muted">{m.label}</span>
            <span className="text-sm font-semibold text-fin-text tabular-nums mt-0.5">
              {m.value}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default ValuationGrid;
