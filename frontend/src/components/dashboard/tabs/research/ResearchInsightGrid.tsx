/**
 * ResearchInsightGrid - TradingKey 风格结构化洞察卡片网格
 *
 * 展示 5 张 AI 洞察卡片（financial / technical / news / peers / overview）。
 * 每张卡片包含：评分环 + 标签 + 关键指标 + 简述 + 风险。
 * overview 由 ResearchOverviewBar 独立展示，此处不重复。
 *
 * 排列顺序：财务诊断 → 技术分析 → 新闻情绪 → 行业对比
 */
import type { InsightCard } from '../../../../types/dashboard';
import { InsightScoreRing } from '../shared/InsightScoreRing';
import { InsightSkeleton } from '../shared/InsightSkeleton';

// ==================== 卡片配置 ====================

interface CardConfig {
  key: string;     // insights dict 中的 key
  label: string;
  icon: string;
}

const CARD_ORDER: CardConfig[] = [
  { key: 'financial', label: '财务诊断', icon: '💰' },
  { key: 'technical', label: '价格动量', icon: '📈' },
  { key: 'news',      label: '新闻情绪', icon: '📰' },
  { key: 'peers',     label: '行业对比', icon: '🏢' },
];

// ==================== Props ====================

interface ResearchInsightGridProps {
  insights: Record<string, InsightCard> | null;
  loading?: boolean;
  error?: string | null;
  stale?: boolean;
}

// ==================== 单卡子组件 ====================

function MetricTag({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between py-1 border-b border-fin-border/20 last:border-b-0">
      <span className="text-2xs text-fin-muted truncate">{label}</span>
      <span className="text-2xs font-semibold text-fin-text ml-2 whitespace-nowrap">
        {value}
      </span>
    </div>
  );
}

function ResearchCard({
  config,
  insight,
  stale,
}: {
  config: CardConfig;
  insight: InsightCard | undefined;
  stale: boolean;
}) {
  if (!insight) return null;

  const scoreColor =
    insight.score >= 7
      ? 'text-fin-success'
      : insight.score >= 4
        ? 'text-fin-warning'
        : 'text-fin-danger';

  return (
    <div
      className={`bg-fin-card rounded-xl border p-4 flex flex-col transition-all duration-300 hover:border-fin-primary/30 ${
        stale ? 'border-fin-border/50 opacity-90' : 'border-fin-border'
      }`}
    >
      {/* 顶部：icon + 标题 + 评分环 */}
      <div className="flex items-center gap-3 mb-3">
        <InsightScoreRing score={insight.score} size={44} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <span className="text-sm">{config.icon}</span>
            <span className="text-sm font-medium text-fin-text truncate">
              {config.label}
            </span>
          </div>
          <div className="flex items-center gap-2 mt-0.5">
            <span className={`text-xs font-semibold ${scoreColor}`}>
              {insight.score_label}
            </span>
            {!insight.model_generated && (
              <span className="text-2xs text-fin-muted bg-fin-border/30 px-1.5 py-0.5 rounded">
                规则
              </span>
            )}
          </div>
        </div>
      </div>

      {/* 关键指标列表 */}
      {insight.key_metrics && insight.key_metrics.length > 0 && (
        <div className="mb-3 px-1">
          {insight.key_metrics.map((m, i) => (
            <MetricTag key={i} label={m.label} value={m.value} />
          ))}
        </div>
      )}

      {/* 摘要 */}
      {insight.summary && (
        <p className="text-xs text-fin-text/80 leading-relaxed line-clamp-3 mb-2">
          {insight.summary}
        </p>
      )}

      {/* 亮点 */}
      {insight.key_points.length > 0 && (
        <ul className="space-y-0.5 mb-2">
          {insight.key_points.slice(0, 3).map((point, i) => (
            <li
              key={i}
              className="flex items-start gap-1.5 text-2xs text-fin-text/70"
            >
              <span className="text-fin-success mt-0.5 flex-shrink-0">•</span>
              <span className="line-clamp-1">{point}</span>
            </li>
          ))}
        </ul>
      )}

      {/* 底部间隔弹簧 + 风险 */}
      <div className="mt-auto" />
      {insight.risks.length > 0 && (
        <div className="pt-2 border-t border-fin-border/40 mt-2">
          {insight.risks.slice(0, 2).map((risk, i) => (
            <div
              key={i}
              className="flex items-start gap-1.5 text-2xs text-fin-danger/80"
            >
              <span className="mt-0.5 flex-shrink-0">⚠</span>
              <span className="line-clamp-1">{risk}</span>
            </div>
          ))}
        </div>
      )}

      {/* 来源标签 */}
      <div className="flex items-center justify-between mt-2 pt-1.5 border-t border-fin-border/20">
        <span className="text-2xs text-fin-muted">
          {insight.model_generated ? 'AI 分析' : '规则评分'}
        </span>
        {stale && (
          <span className="text-2xs text-fin-muted flex items-center gap-0.5">
            <span className="opacity-60">🕐</span>
            已过期
          </span>
        )}
      </div>
    </div>
  );
}

// ==================== 主网格组件 ====================

export function ResearchInsightGrid({
  insights,
  loading = false,
  error = null,
  stale = false,
}: ResearchInsightGridProps) {
  // 加载骨架
  if (loading && !insights) {
    return (
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {CARD_ORDER.map((c) => (
          <InsightSkeleton key={c.key} />
        ))}
      </div>
    );
  }

  // 错误态
  if (error && !insights) {
    return (
      <div className="bg-fin-card rounded-xl border border-fin-border p-6 text-center">
        <p className="text-sm text-fin-muted">AI 洞察暂不可用</p>
        <p className="text-xs text-fin-muted/60 mt-1">{error}</p>
      </div>
    );
  }

  if (!insights) return null;

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
      {CARD_ORDER.map((config) => (
        <ResearchCard
          key={config.key}
          config={config}
          insight={insights[config.key]}
          stale={stale}
        />
      ))}
    </div>
  );
}

export default ResearchInsightGrid;
