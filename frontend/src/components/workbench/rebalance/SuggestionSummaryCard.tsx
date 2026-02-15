/**
 * SuggestionSummaryCard — Displays the AI-generated summary, expected impact
 * metrics, risk tier badge, and action count statistics for a rebalance suggestion.
 */
import { Brain, TrendingUp, Shield, Activity } from 'lucide-react';

import { Badge } from '../../ui/Badge.tsx';
import type { RebalanceSuggestion, RiskTier } from '../../../types/dashboard.ts';

interface SuggestionSummaryCardProps {
  suggestion: RebalanceSuggestion;
}

const RISK_TIER_CONFIG: Record<RiskTier, { label: string; variant: 'success' | 'warning' | 'danger' }> = {
  conservative: { label: '保守型', variant: 'success' },
  moderate: { label: '稳健型', variant: 'warning' },
  aggressive: { label: '进取型', variant: 'danger' },
};

export function SuggestionSummaryCard({ suggestion }: SuggestionSummaryCardProps) {
  const riskConfig = RISK_TIER_CONFIG[suggestion.risk_tier];
  const impact = suggestion.expected_impact;
  const actionCount = suggestion.actions.length;
  const buyCount = suggestion.actions.filter((a) => a.action === 'buy' || a.action === 'increase').length;
  const sellCount = suggestion.actions.filter((a) => a.action === 'sell' || a.action === 'reduce').length;

  return (
    <div className="space-y-3">
      {/* Header: risk tier badge + stats */}
      <div className="flex items-center gap-3 flex-wrap">
        <Badge variant={riskConfig.variant}>{riskConfig.label}</Badge>
        <span className="text-2xs text-fin-muted">
          共 {actionCount} 项操作
        </span>
        {buyCount > 0 && (
          <span className="text-2xs text-emerald-500">
            +{buyCount} 买入/增持
          </span>
        )}
        {sellCount > 0 && (
          <span className="text-2xs text-red-400">
            -{sellCount} 卖出/减持
          </span>
        )}
      </div>

      {/* AI summary */}
      <div className="flex items-start gap-2">
        <Brain size={14} className="shrink-0 mt-0.5 text-fin-primary" />
        <p className="text-sm text-fin-text leading-relaxed">{suggestion.summary}</p>
      </div>

      {/* Expected impact metrics */}
      <div className="grid grid-cols-3 gap-3">
        <ImpactMetric
          icon={<TrendingUp size={14} />}
          label="分散化"
          value={impact.diversification_delta}
        />
        <ImpactMetric
          icon={<Shield size={14} />}
          label="风险变化"
          value={impact.risk_delta}
        />
        <ImpactMetric
          icon={<Activity size={14} />}
          label="预计换手率"
          value={`${impact.estimated_turnover_pct.toFixed(1)}%`}
        />
      </div>

      {/* Warnings */}
      {suggestion.warnings.length > 0 && (
        <ul className="space-y-1">
          {suggestion.warnings.map((w, i) => (
            <li key={i} className="text-2xs text-amber-500 flex items-start gap-1.5">
              <span className="shrink-0">!</span>
              <span>{w}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/* ---- Internal metric display ---- */

interface ImpactMetricProps {
  icon: React.ReactNode;
  label: string;
  value: string;
}

function ImpactMetric({ icon, label, value }: ImpactMetricProps) {
  return (
    <div className="flex flex-col items-center gap-1 px-2 py-2 rounded-lg bg-fin-bg-secondary">
      <span className="text-fin-muted">{icon}</span>
      <span className="text-2xs text-fin-muted">{label}</span>
      <span className="text-xs font-semibold text-fin-text">{value}</span>
    </div>
  );
}
