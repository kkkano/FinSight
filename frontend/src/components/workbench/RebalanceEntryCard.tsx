/**
 * RebalanceEntryCard — Entry card shown on the Workbench page.
 *
 * When no suggestion exists: shows the parameter panel with a "Generate" CTA.
 * When a suggestion exists: shows a summary preview with "View Details" and "Regenerate".
 * Internally uses hooks for portfolio data and rebalance suggestion state.
 */
import { useState, useCallback, useMemo } from 'react';
import { Scale, Eye, RefreshCw, Loader2, AlertCircle } from 'lucide-react';

import { Card } from '../ui/Card.tsx';
import { Button } from '../ui/Button.tsx';
import { Badge } from '../ui/Badge.tsx';
import { useStore } from '../../store/useStore.ts';
import { useRebalanceSuggestion } from '../../hooks/useRebalanceSuggestion.ts';
import { RebalanceParamPanel } from './rebalance/RebalanceParamPanel.tsx';
import { RebalanceResultView } from './rebalance/RebalanceResultView.tsx';
import type { GenerateRebalanceParams, RiskTier } from '../../types/dashboard.ts';

const RISK_TIER_LABELS: Record<RiskTier, string> = {
  conservative: '保守型',
  moderate: '稳健型',
  aggressive: '进取型',
};

export function RebalanceEntryCard() {
  const sessionId = useStore((s) => s.sessionId);
  const portfolioPositions = useStore((s) => s.portfolioPositions);

  const { suggestion, loading, error, generate, updateStatus, clear } =
    useRebalanceSuggestion();

  const [showDetails, setShowDetails] = useState(false);

  // Convert portfolioPositions map to the array format expected by API
  const portfolio = useMemo(
    () =>
      Object.entries(portfolioPositions).map(([ticker, shares]) => ({
        ticker,
        shares,
      })),
    [portfolioPositions],
  );

  const handleGenerate = useCallback(
    (params: GenerateRebalanceParams) => {
      setShowDetails(false);
      generate(params);
    },
    [generate],
  );

  const handleRegenerate = useCallback(() => {
    clear();
    setShowDetails(false);
  }, [clear]);

  const handleViewDetails = useCallback(() => {
    setShowDetails(true);
  }, []);

  // No suggestion yet — show param panel
  if (!suggestion && !showDetails) {
    return (
      <div className="space-y-3">
        <Card className="p-4">
          <div className="flex items-center gap-2 mb-3 text-fin-text font-semibold text-sm">
            <Scale size={16} className="text-fin-primary" />
            AI 智能调仓
          </div>
          <p className="text-xs text-fin-muted mb-3">
            基于持仓分析和市场数据，生成个性化调仓建议。仅供参考，不构成投资建议。
          </p>

          {error && (
            <div className="flex items-center gap-2 text-xs text-red-500 mb-3">
              <AlertCircle size={14} />
              {error}
            </div>
          )}

          {loading && (
            <div className="flex items-center gap-2 text-xs text-fin-muted py-2">
              <Loader2 size={14} className="animate-spin text-fin-primary" />
              正在分析持仓并生成建议...
            </div>
          )}
        </Card>

        <RebalanceParamPanel
          loading={loading}
          onGenerate={handleGenerate}
          sessionId={sessionId}
          portfolio={portfolio}
        />
      </div>
    );
  }

  // Suggestion exists — show summary preview or full details
  if (suggestion && !showDetails) {
    return (
      <Card className="p-4 space-y-3">
        <div className="flex items-center gap-2 text-fin-text font-semibold text-sm">
          <Scale size={16} className="text-fin-primary" />
          AI 智能调仓
          <Badge variant="info" className="ml-auto">
            {RISK_TIER_LABELS[suggestion.risk_tier]}
          </Badge>
        </div>

        <p className="text-xs text-fin-text-secondary leading-relaxed line-clamp-3">
          {suggestion.summary}
        </p>

        <div className="flex items-center gap-2 text-2xs text-fin-muted">
          <span>{suggestion.actions.length} 项操作建议</span>
          <span className="text-fin-border">|</span>
          <span>换手率 {suggestion.expected_impact.estimated_turnover_pct.toFixed(1)}%</span>
        </div>

        <div className="flex items-center gap-2 pt-1">
          <Button variant="primary" size="sm" onClick={handleViewDetails}>
            <Eye size={14} />
            查看详情
          </Button>
          <Button variant="ghost" size="sm" onClick={handleRegenerate}>
            <RefreshCw size={14} />
            重新生成
          </Button>
        </div>
      </Card>
    );
  }

  // Full detail view
  if (suggestion && showDetails) {
    return (
      <div className="space-y-3">
        <RebalanceResultView
          suggestion={suggestion}
          onUpdateStatus={updateStatus}
          onRegenerate={handleRegenerate}
        />
        <RebalanceParamPanel
          loading={loading}
          onGenerate={handleGenerate}
          sessionId={sessionId}
          portfolio={portfolio}
        />
      </div>
    );
  }

  return null;
}
