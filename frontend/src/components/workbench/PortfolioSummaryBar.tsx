import { useMemo } from 'react';
import { BarChart3, Briefcase, TrendingDown, TrendingUp } from 'lucide-react';

import { useStore } from '../../store/useStore';
import { usePortfolioSummary } from '../../hooks/usePortfolioSummary';
import { Skeleton } from '../ui';

interface SummaryMetric {
  label: string;
  value: string;
  icon: React.ReactNode;
  color?: string;
}

const formatCurrency = (value: number | null | undefined): string => {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  const abs = Math.abs(value);
  if (abs >= 1_000_000_000) return `$${(value / 1_000_000_000).toFixed(2)}B`;
  if (abs >= 1_000_000) return `$${(value / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `$${(value / 1_000).toFixed(2)}K`;
  return `$${value.toFixed(2)}`;
};

export function PortfolioSummaryBar() {
  const sessionId = useStore((s) => s.sessionId);
  const { data, loading } = usePortfolioSummary(sessionId);

  const metrics = useMemo((): SummaryMetric[] => {
    const positions = data?.positions ?? [];
    const holdingCount = data?.count ?? 0;
    const largestHolding = [...positions]
      .sort((a, b) => (b.market_value ?? 0) - (a.market_value ?? 0))[0];

    const totalValue = data?.total_value ?? null;
    const totalDayChange = data?.total_day_change ?? null;
    const dayChangeColor =
      totalDayChange === null || totalDayChange === undefined
        ? 'text-fin-muted'
        : totalDayChange >= 0
          ? 'text-fin-success'
          : 'text-fin-danger';

    return [
      { label: 'Positions', value: String(holdingCount), icon: <Briefcase size={14} /> },
      { label: 'Total Value', value: formatCurrency(totalValue), icon: <BarChart3 size={14} /> },
      { label: 'Today P&L', value: formatCurrency(totalDayChange), icon: <TrendingUp size={14} />, color: dayChangeColor },
      { label: 'Largest Holding', value: largestHolding?.ticker ?? '--', icon: <TrendingDown size={14} /> },
    ];
  }, [data]);

  return (
    <div className="flex items-center gap-6 px-4 py-2.5 bg-fin-card border border-fin-border rounded-xl overflow-x-auto scrollbar-hide">
      {metrics.map((metric) => (
        <div key={metric.label} className="flex items-center gap-2 whitespace-nowrap">
          <span className="text-fin-text-secondary">{metric.icon}</span>
          <span className="text-xs text-fin-muted">{metric.label}</span>
          {loading ? (
            <Skeleton variant="rectangular" className="w-20 h-3" />
          ) : (
            <span className={`text-xs font-semibold ${metric.color ?? 'text-fin-text'}`}>{metric.value}</span>
          )}
        </div>
      ))}
    </div>
  );
}
