import { useMemo } from 'react';
import { BarChart3, Briefcase, Crown, MessageCircle, TrendingUp } from 'lucide-react';

import { useStore } from '../../store/useStore';
import { usePortfolioSummary } from '../../hooks/usePortfolioSummary';
import { Skeleton } from '../ui';
import { formatCurrency } from '../../utils/format';
import { useChatHandoff } from '../../hooks/useChatHandoff';

interface SummaryMetric {
  label: string;
  value: string;
  icon: React.ReactNode;
  color?: string;
}

export function PortfolioSummaryBar() {
  const handoffToChat = useChatHandoff();
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
      { label: '持仓数', value: String(holdingCount), icon: <Briefcase size={14} /> },
      { label: '总市值', value: formatCurrency(totalValue), icon: <BarChart3 size={14} /> },
      { label: '今日盈亏', value: formatCurrency(totalDayChange), icon: <TrendingUp size={14} />, color: dayChangeColor },
      { label: '最大持仓', value: largestHolding?.ticker ?? '--', icon: <Crown size={14} /> },
    ];
  }, [data]);

  return (
    <div className="flex items-center gap-6 px-4 py-2.5 bg-fin-card border border-fin-border rounded-lg overflow-x-auto scrollbar-hide">
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
      <button
        type="button"
        onClick={() => handoffToChat({
          draft: '我的持仓该怎么调整？',
          sourceView: 'workbench',
          sourceTab: 'portfolio',
        })}
        className="ml-auto inline-flex min-h-11 shrink-0 items-center gap-1.5 rounded-lg px-3 text-xs font-medium text-fin-primary transition-colors hover:bg-fin-primary/10"
        data-testid="portfolio-analyze-in-chat"
      >
        <MessageCircle size={14} />
        分析我的持仓
      </button>
    </div>
  );
}
