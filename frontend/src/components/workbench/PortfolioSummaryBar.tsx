/**
 * PortfolioSummaryBar — Compact horizontal bar showing portfolio overview.
 *
 * Displays: Total Value | Today P&L | Position Count | Largest Holding
 */
import { useMemo } from 'react';
import { TrendingUp, TrendingDown, Briefcase, BarChart3 } from 'lucide-react';

import { useStore } from '../../store/useStore';

interface PositionEntry {
  symbol: string;
  shares: number;
}

interface SummaryMetric {
  label: string;
  value: string;
  icon: React.ReactNode;
  color?: string;
}

export function PortfolioSummaryBar() {
  const rawPositions = useStore((s) => s.portfolioPositions) ?? {};

  // Convert Record<string, number> → PositionEntry[]
  const positions: PositionEntry[] = useMemo(
    () => Object.entries(rawPositions).map(([symbol, shares]) => ({ symbol, shares })),
    [rawPositions],
  );

  const metrics = useMemo((): SummaryMetric[] => {
    if (positions.length === 0) {
      return [
        { label: '持仓数', value: '0', icon: <Briefcase size={14} /> },
        { label: '总市值', value: '--', icon: <BarChart3 size={14} /> },
        { label: '今日盈亏', value: '--', icon: <TrendingUp size={14} /> },
        { label: '最大持仓', value: '--', icon: <BarChart3 size={14} /> },
      ];
    }

    const largest = positions.reduce(
      (max, p) => (p.shares > max.shares ? p : max),
      positions[0],
    );

    return [
      { label: '持仓数', value: String(positions.length), icon: <Briefcase size={14} /> },
      {
        label: '总市值',
        value: '--',
        icon: <BarChart3 size={14} />,
      },
      {
        label: '今日盈亏',
        value: '--',
        icon: <TrendingUp size={14} />,
        color: 'text-fin-muted',
      },
      {
        label: '最大持仓',
        value: largest.symbol,
        icon: <TrendingDown size={14} />,
      },
    ];
  }, [positions]);

  return (
    <div className="flex items-center gap-6 px-4 py-2.5 bg-fin-card border border-fin-border rounded-xl overflow-x-auto scrollbar-none">
      {metrics.map((m) => (
        <div key={m.label} className="flex items-center gap-2 whitespace-nowrap">
          <span className="text-fin-text-secondary">{m.icon}</span>
          <span className="text-xs text-fin-muted">{m.label}</span>
          <span className={`text-xs font-semibold ${m.color ?? 'text-fin-text'}`}>
            {m.value}
          </span>
        </div>
      ))}
    </div>
  );
}
