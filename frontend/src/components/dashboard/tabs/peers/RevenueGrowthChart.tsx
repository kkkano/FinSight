/**
 * RevenueGrowthChart - CSS-based horizontal bar chart for revenue growth comparison.
 *
 * Highlights the current stock in primary color.
 * Handles negative growth values with left-aligned bars.
 */
import { useMemo } from 'react';

import type { PeerMetrics } from '../../../../types/dashboard.ts';

interface RevenueGrowthChartProps {
  peers: PeerMetrics[];
  subjectSymbol: string;
}

export function RevenueGrowthChart({ peers, subjectSymbol }: RevenueGrowthChartProps) {
  const chartData = useMemo(() => {
    const withGrowth = peers
      .filter((p) => p.revenue_growth != null)
      .map((p) => ({
        symbol: p.symbol,
        value: (p.revenue_growth as number) * 100,
        isCurrent: p.symbol.toUpperCase() === subjectSymbol.toUpperCase(),
      }))
      .sort((a, b) => b.value - a.value);

    const maxAbs = withGrowth.length > 0
      ? Math.max(...withGrowth.map((d) => Math.abs(d.value)), 1)
      : 1;

    return withGrowth.map((d) => ({
      ...d,
      pct: (Math.abs(d.value) / maxAbs) * 50,
      isNegative: d.value < 0,
    }));
  }, [peers, subjectSymbol]);

  if (chartData.length === 0) {
    return (
      <div className="flex items-center justify-center h-32 text-fin-muted text-sm">
        暂无营收增长数据
      </div>
    );
  }

  return (
    <div className="bg-fin-card border border-fin-border rounded-lg p-4">
      <h4 className="text-sm font-semibold text-fin-text mb-3">营收增长对比</h4>
      <div className="space-y-2">
        {chartData.map((item) => (
          <div key={item.symbol} className="flex items-center gap-3">
            <span className={`text-xs w-14 text-right shrink-0 ${
              item.isCurrent ? 'text-fin-primary font-semibold' : 'text-fin-muted'
            }`}>
              {item.symbol}
            </span>
            <div className="flex-1 h-5 relative bg-fin-border/30 rounded overflow-hidden">
              {/* Center line for zero reference */}
              <div className="absolute left-1/2 top-0 bottom-0 w-px bg-fin-border" />
              {/* Bar */}
              <div
                className={`absolute top-0 h-full rounded transition-all duration-500 ${
                  item.isCurrent
                    ? item.isNegative ? 'bg-fin-danger' : 'bg-amber-500'
                    : item.isNegative ? 'bg-fin-danger/40' : 'bg-fin-success/40'
                }`}
                style={
                  item.isNegative
                    ? { right: '50%', width: `${item.pct}%` }
                    : { left: '50%', width: `${item.pct}%` }
                }
              />
            </div>
            <span className={`text-xs w-16 text-right shrink-0 ${
              item.isCurrent ? 'text-fin-primary font-semibold' : 'text-fin-text'
            }`}>
              {item.value >= 0 ? '+' : ''}{item.value.toFixed(1)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default RevenueGrowthChart;
