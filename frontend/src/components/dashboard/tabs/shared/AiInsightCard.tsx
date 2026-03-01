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
import { MessageCircleQuestion, RefreshCw } from 'lucide-react';

import type { InsightCard, SelectionItem } from '../../../../types/dashboard';
import { CardInfoTip } from '../../../ui/CardInfoTip';
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

const EVIDENCE_DIAGNOSTIC_KEYWORDS = [
  '质量门槛',
  '证据',
  '引用',
  'citation',
  '10-k',
  '10-q',
  '业绩电话会',
  '纪要',
  '路透',
  'reuters',
  'bloomberg',
  'wsj',
  'ft',
  'cnbc',
  'yahoo',
  '摘录',
  '交叉引用',
];

const EXECUTION_DIAGNOSTIC_KEYWORDS = [
  'agent',
  'diagnostic',
  'orchestration',
  'policy',
  'analysis_depth',
  'conflict',
  '未运行',
  '未执行',
  '冲突',
  '裁决',
  '可信度受限',
  '调度',
];

const collectInsightText = (insight: InsightCard): string => (
  [
    insight.summary ?? '',
    ...(Array.isArray(insight.key_points) ? insight.key_points : []),
    ...(Array.isArray(insight.risks) ? insight.risks : []),
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
);

const isEvidenceDiagnosticInsight = (insight: InsightCard): boolean => {
  const content = collectInsightText(insight);
  return EVIDENCE_DIAGNOSTIC_KEYWORDS.some((token) => content.includes(token));
};

const isExecutionDiagnosticInsight = (insight: InsightCard): boolean => {
  const content = collectInsightText(insight);
  return EXECUTION_DIAGNOSTIC_KEYWORDS.some((token) => content.includes(token));
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
  /** Callback when user wants to ask about this insight */
  onAskAbout?: (selection: SelectionItem) => void;
  /** Callback to force-refresh the AI insights */
  onRefresh?: () => void;
  actionSuggestion?: {
    action: string;
    rationale?: string | null;
    entryRange?: string | null;
    takeProfit?: string | null;
    stopLoss?: string | null;
  } | null;
}

// --- Component ---

export function AiInsightCard({
  tab,
  insight,
  loading = false,
  error = null,
  stale = false,
  compact = false,
  onAskAbout,
  onRefresh,
  actionSuggestion = null,
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
  const evidenceDiagnostic = isEvidenceDiagnosticInsight(insight);
  const executionDiagnostic = isExecutionDiagnosticInsight(insight);
  const diagnosticInsight = evidenceDiagnostic || executionDiagnostic;

  const diagnosticTipContent = evidenceDiagnostic
    ? (
      <div className="space-y-1">
        <div>原因：该卡片当前是证据质量诊断，不是金融结论。</div>
        <div>影响：结论可信度受限，建议先不要直接用于交易决策。</div>
        <div>恢复：补齐 10-K/10-Q、业绩会与权威媒体摘录后重跑。</div>
      </div>
    )
    : (
      <div className="space-y-1">
        <div>原因：该卡片当前是执行诊断，不是金融结论。</div>
        <div>影响：部分 Agent 未运行/降级，综合分析完整性下降。</div>
        <div>恢复：调整策略或深度配置后刷新重跑。</div>
      </div>
    );

  return (
    <div
      className={`bg-fin-card rounded-xl border p-4 transition-all duration-300 ${
        stale ? 'border-fin-border/50 opacity-90' : 'border-fin-border'
      }`}
    >
      {/* Header: icon + title + score ring + ask button */}
      <div className="flex items-center gap-3 mb-3">
        <InsightScoreRing score={insight.score} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <span className="text-sm">{icon}</span>
            <span className="text-sm font-medium text-fin-text truncate">
              {label}
            </span>
            <CardInfoTip content="基于 Digest Agent 对实时数据的 AI 分析，含评分、摘要和操作建议" />
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
        {onAskAbout && !diagnosticInsight && (
          <button
            type="button"
            title="问这条"
            aria-label={`询问关于 ${label}`}
            className="p-1.5 rounded-lg text-fin-muted hover:bg-fin-primary/10 hover:text-fin-primary transition-all shrink-0"
            onClick={() => {
              const selection: SelectionItem = {
                type: 'insight',
                id: `insight-${tab}-${insight.as_of ?? Date.now()}`,
                title: `${label}：${insight.score_label}（${insight.score}/10）`,
                snippet: insight.summary?.slice(0, 100) ?? '',
              };
              onAskAbout(selection);
            }}
          >
            <MessageCircleQuestion size={15} />
          </button>
        )}
        {diagnosticInsight && (
          <CardInfoTip
            icon="alert"
            size={15}
            className="shrink-0"
            content={diagnosticTipContent}
          />
        )}
        {onRefresh && (
          <button
            type="button"
            title="刷新 AI 分析"
            aria-label="刷新 AI 分析"
            className="p-1.5 rounded-lg text-fin-muted hover:bg-fin-primary/10 hover:text-fin-primary transition-all shrink-0"
            onClick={onRefresh}
          >
            <RefreshCw size={13} />
          </button>
        )}
      </div>

      {/* Summary */}
      {!compact && insight.summary && (
        <p className="text-xs text-fin-text/80 leading-relaxed mb-3 line-clamp-4">
          {insight.summary}
        </p>
      )}

      {/* Overview action suggestion */}
      {!compact && tab === 'overview' && actionSuggestion?.action && (
        <div className="mb-3 rounded-lg border border-fin-border/60 bg-fin-border/20 p-2.5">
          <div className="text-xs font-semibold text-fin-text">
            操作建议：{actionSuggestion.action}
          </div>
          {actionSuggestion.rationale && (
            <div className="mt-1 text-2xs text-fin-muted leading-relaxed">
              {actionSuggestion.rationale}
            </div>
          )}
          <div className="mt-2 flex flex-wrap gap-1.5">
            {actionSuggestion.entryRange && (
              <span className="text-2xs text-fin-text bg-fin-card/70 border border-fin-border/60 rounded px-1.5 py-0.5">
                买入参考：{actionSuggestion.entryRange}
              </span>
            )}
            {actionSuggestion.takeProfit && (
              <span className="text-2xs text-fin-text bg-fin-card/70 border border-fin-border/60 rounded px-1.5 py-0.5">
                止盈参考：{actionSuggestion.takeProfit}
              </span>
            )}
            {actionSuggestion.stopLoss && (
              <span className="text-2xs text-fin-text bg-fin-card/70 border border-fin-border/60 rounded px-1.5 py-0.5">
                风险位：{actionSuggestion.stopLoss}
              </span>
            )}
          </div>
        </div>
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
