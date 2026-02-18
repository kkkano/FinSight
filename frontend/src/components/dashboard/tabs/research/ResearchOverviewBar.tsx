/**
 * ResearchOverviewBar - 综合评估总览横条
 *
 * 展示 AI 综合评分（overview）的大号环形分、评价标签、置信度。
 * 当 overview insight 缺失时显示 skeleton 占位。
 */
import type { InsightCard } from '../../../../types/dashboard';
import { InsightScoreRing } from '../shared/InsightScoreRing';

// ==================== Props ====================

interface ResearchOverviewBarProps {
  overview: InsightCard | null | undefined;
  loading?: boolean;
}

// ==================== 组件 ====================

export function ResearchOverviewBar({
  overview,
  loading = false,
}: ResearchOverviewBarProps) {
  // 加载中骨架
  if (loading && !overview) {
    return (
      <div className="bg-fin-card rounded-xl border border-fin-border p-5 animate-pulse">
        <div className="flex items-center gap-5">
          <div className="w-16 h-16 rounded-full bg-fin-border" />
          <div className="flex-1 space-y-2">
            <div className="h-5 w-48 bg-fin-border rounded" />
            <div className="h-3 w-full bg-fin-border rounded" />
            <div className="h-3 w-3/4 bg-fin-border rounded" />
          </div>
        </div>
      </div>
    );
  }

  if (!overview) return null;

  const scoreColor =
    overview.score >= 7
      ? 'text-fin-success'
      : overview.score >= 4
        ? 'text-fin-warning'
        : 'text-fin-danger';

  return (
    <div className="bg-fin-card rounded-xl border border-fin-border p-5">
      <div className="flex items-center gap-5">
        {/* 大号评分环 */}
        <InsightScoreRing score={overview.score} size={64} />

        <div className="flex-1 min-w-0">
          {/* 标题行：评价标签 + 置信度 */}
          <div className="flex items-center gap-3 mb-1">
            <span className="text-sm">🌍</span>
            <h3 className="text-base font-semibold text-fin-text">
              综合评估
            </h3>
            <span className={`text-sm font-bold ${scoreColor}`}>
              {overview.score_label}
            </span>
            {!overview.model_generated && (
              <span className="text-2xs text-fin-muted bg-fin-border/30 px-1.5 py-0.5 rounded">
                规则评分
              </span>
            )}
          </div>

          {/* 摘要 */}
          <p className="text-xs text-fin-text/80 leading-relaxed line-clamp-3">
            {overview.summary}
          </p>

          {/* 关键指标条 */}
          {overview.key_metrics && overview.key_metrics.length > 0 && (
            <div className="flex flex-wrap gap-3 mt-2">
              {overview.key_metrics.map((m, i) => (
                <div
                  key={i}
                  className="flex items-center gap-1 text-2xs text-fin-muted"
                >
                  <span className="text-fin-text/60">{m.label}:</span>
                  <span className="font-medium text-fin-text">{m.value}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default ResearchOverviewBar;
