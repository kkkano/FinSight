/**
 * ValuationBarChart - CSS-based horizontal bar chart for PE comparison.
 *
 * Highlights the current stock in orange / primary color.
 */
import { useMemo } from 'react';

import type { PeerMetrics } from '../../../../types/dashboard.ts';

interface ValuationBarChartProps {
  peers: PeerMetrics[];
  subjectSymbol: string;
}

export function ValuationBarChart({ peers, subjectSymbol }: ValuationBarChartProps) {
  const chartData = useMemo(() => {
    const withPE = peers
      .filter((p) => p.trailing_pe != null && p.trailing_pe > 0)
      .map((p) => ({
        symbol: p.symbol,
        value: p.trailing_pe as number,
        isCurrent: p.symbol.toUpperCase() === subjectSymbol.toUpperCase(),
      }))
      .sort((a, b) => b.value - a.value);

    const maxVal = withPE.length > 0 ? Math.max(...withPE.map((d) => d.value)) : 1;
    return withPE.map((d) => ({
      ...d,
      pct: maxVal > 0 ? (d.value / maxVal) * 100 : 0,
    }));
  }, [peers, subjectSymbol]);

  if (chartData.length === 0) {
    return (
      <div className="flex items-center justify-center h-32 text-fin-muted text-sm">
        暂无市盈率数据
      </div>
    );
  }

  return (
    <div className="bg-fin-card border border-fin-border rounded-lg p-4">
      <h4 className="text-sm font-semibold text-fin-text mb-3">P/E 对比</h4>
      <div className="space-y-2">
        {chartData.map((item) => (
          <div key={item.symbol} className="flex items-center gap-3">
            <span className={`text-xs w-14 text-right shrink-0 ${
              item.isCurrent ? 'text-fin-primary font-semibold' : 'text-fin-muted'
            }`}>
              {item.symbol}
            </span>
            <div className="flex-1 h-5 bg-fin-border/30 rounded overflow-hidden">
              <div
                className={`h-full rounded transition-all duration-500 ${
                  item.isCurrent ? 'bg-amber-500' : 'bg-fin-primary/40'
                }`}
                style={{ width: `${item.pct}%` }}
              />
            </div>
            <span className={`text-xs w-12 text-right shrink-0 ${
              item.isCurrent ? 'text-fin-primary font-semibold' : 'text-fin-text'
            }`}>
              {item.value.toFixed(1)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default ValuationBarChart;
