/**
 * AiInsightCard - Unified AI analysis card for Dashboard tabs.
 *
 * Displays LLM-generated (or deterministic fallback) insights with:
 * - Score ring + label
 * - Summary text
 * - Key points list
 * - Risk warnings
 * - Stale/fallback indicators
 *
 * Four states: loading → loaded → stale → error
 */
import type { InsightCard } from '../../../../types/dashboard';
import { InsightScoreRing } from './InsightScoreRing';
import { InsightSkeleton } from './InsightSkeleton';

// --- Tab display config ---

const TAB_LABELS: Record<string, string> = {
  overview: 'AI 综合评估',
  financial: 'AI 财务分析',
  technical: 'AI 技术分析',
  news: 'AI 舆情分析',
  peers: 'AI 同行对比',
};

const TAB_ICONS: Record<string, string> = {
  overview: '📊',
  financial: '💰',
  technical: '📈',
  news: '📰',
  peers: '🏢',
};

// --- Props ---

interface AiInsightCardProps {
  tab: string;
  insight: InsightCard | null | undefined;
  loading?: boolean;
  error?: string | null;
  stale?: boolean;
  /** Compact mode hides summary, only shows key points */
  compact?: boolean;
}

// --- Component ---

export function AiInsightCard({
  tab,
  insight,
  loading = false,
  error = null,
  stale = false,
  compact = false,
}: AiInsightCardProps) {
  // Loading state
  if (loading && !insight) {
    return <InsightSkeleton />;
  }

  // Error state (no cached insight available)
  if (error && !insight) {
    return (
      <div className="bg-fin-card rounded-xl border border-fin-border p-4">
        <div className="flex items-center gap-2 text-fin-muted text-sm">
          <span>{TAB_ICONS[tab] ?? '🤖'}</span>
          <span>{TAB_LABELS[tab] ?? 'AI 分析'}</span>
        </div>
        <p className="text-fin-muted text-xs mt-2">
          AI 分析暂不可用
        </p>
      </div>
    );
  }

  // No insight data
  if (!insight) return null;

  const label = TAB_LABELS[tab] ?? 'AI 分析';
  const icon = TAB_ICONS[tab] ?? '🤖';

  return (
    <div
      className={`bg-fin-card rounded-xl border p-4 transition-all duration-300 ${
        stale ? 'border-fin-border/50 opacity-90' : 'border-fin-border'
      }`}
    >
      {/* Header: icon + title + score ring */}
      <div className="flex items-center gap-3 mb-3">
        <InsightScoreRing score={insight.score} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <span className="text-sm">{icon}</span>
            <span className="text-sm font-medium text-fin-text truncate">
              {label}
            </span>
          </div>
          <div className="flex items-center gap-2 mt-0.5">
            <span
              className={`text-xs font-semibold ${
                insight.score >= 7
                  ? 'text-fin-success'
                  : insight.score >= 4
                    ? 'text-fin-warning'
                    : 'text-fin-danger'
              }`}
            >
              {insight.score_label}
            </span>
            {!insight.model_generated && (
              <span className="text-2xs text-fin-muted bg-fin-border/30 px-1.5 py-0.5 rounded">
                规则评分
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Summary */}
      {!compact && insight.summary && (
        <p className="text-xs text-fin-text/80 leading-relaxed mb-3 line-clamp-4">
          {insight.summary}
        </p>
      )}

      {/* Key Points */}
      {insight.key_points.length > 0 && (
        <ul className="space-y-1 mb-2">
          {insight.key_points.map((point, i) => (
            <li
              key={i}
              className="flex items-start gap-1.5 text-xs text-fin-text/70"
            >
              <span className="text-fin-success mt-0.5 flex-shrink-0">•</span>
              <span className="line-clamp-2">{point}</span>
            </li>
          ))}
        </ul>
      )}

      {/* Risks */}
      {insight.risks.length > 0 && (
        <div className="mt-2 pt-2 border-t border-fin-border/50">
          {insight.risks.map((risk, i) => (
            <div
              key={i}
              className="flex items-start gap-1.5 text-xs text-fin-danger/80"
            >
              <span className="mt-0.5 flex-shrink-0">⚠</span>
              <span className="line-clamp-2">{risk}</span>
            </div>
          ))}
        </div>
      )}

      {/* Footer: source + staleness */}
      <div className="flex items-center justify-between mt-3 pt-2 border-t border-fin-border/30">
        <span className="text-2xs text-fin-muted">
          {insight.model_generated ? '基于 AI 分析' : '基于规则评分'}
        </span>
        {stale && (
          <span className="text-2xs text-fin-muted flex items-center gap-1">
            <span className="opacity-60">🕐</span>
            数据可能已过期
          </span>
        )}
      </div>
    </div>
  );
}

export default AiInsightCard;
