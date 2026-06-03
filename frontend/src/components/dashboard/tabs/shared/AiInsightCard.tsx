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
import { Loader2, MessageCircleQuestion, RefreshCw, Search } from 'lucide-react';

import type { InsightCard, SelectionItem } from '../../../../types/dashboard';
import { CardInfoTip } from '../../../ui/CardInfoTip';
import { InsightScoreRing } from './InsightScoreRing';
import { InsightSkeleton } from './InsightSkeleton';
import { SourceTrustBadge } from '../../../source/SourceTrustBadge';

/** P2-4: 置信度颜色编码（>=0.8 绿 / 0.5-0.8 黄 / <0.5 红） */
export function confidenceColorClass(confidence: number): string {
  if (confidence >= 0.8) return 'text-fin-success';
  if (confidence >= 0.5) return 'text-fin-warning';
  return 'text-fin-danger';
}

/** P2-4: 数据时点短格式（无效时间返回空字符串） */
export function formatAsOf(asOf: string): string {
  const date = new Date(asOf);
  if (Number.isNaN(date.getTime())) return '';
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  const hours = String(date.getHours()).padStart(2, '0');
  const minutes = String(date.getMinutes()).padStart(2, '0');
  return `${month}-${day} ${hours}:${minutes}`;
}

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
  /** Callback to run Dashboard Agent deep dive for this tab */
  onDeepDive?: () => void;
  deepDiveRunning?: boolean;
  deepDiveProgress?: number;
  deepDiveCurrentStep?: string | null;
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
  onDeepDive,
  deepDiveRunning = false,
  deepDiveProgress = 0,
  deepDiveCurrentStep = null,
  onRefresh,
  actionSuggestion = null,
}: AiInsightCardProps) {
  const label = TAB_LABELS[tab] ?? 'AI 分析';
  const icon = TAB_ICONS[tab] ?? '🤖';
  const deepDivePercent = Math.max(0, Math.min(100, deepDiveProgress));

  const renderDeepDiveButton = () => {
    if (!onDeepDive) return null;
    return (
      <button
        type="button"
        title={deepDiveRunning ? 'Agent 深挖进行中' : 'Agent 深挖'}
        aria-label={`${label} Agent 深挖`}
        disabled={deepDiveRunning}
        className={`flex items-center gap-1.5 px-2 py-1.5 rounded-lg text-xs transition-all shrink-0 ${
          deepDiveRunning
            ? 'text-fin-muted bg-fin-border/30 cursor-wait'
            : 'text-fin-primary bg-fin-primary/10 hover:bg-fin-primary/15'
        }`}
        onClick={onDeepDive}
      >
        {deepDiveRunning ? (
          <Loader2 size={13} className="animate-spin" />
        ) : (
          <Search size={13} />
        )}
        <span>深挖</span>
      </button>
    );
  };

  const renderDeepDiveProgress = () => {
    if (!deepDiveRunning) return null;
    return (
      <div className="mb-3 rounded-lg border border-fin-primary/25 bg-fin-primary/5 px-3 py-2">
        <div className="flex items-center justify-between gap-3 text-2xs">
          <span className="text-fin-muted truncate">
            {deepDiveCurrentStep ?? 'Agent 深挖执行中...'}
          </span>
          <span className="text-fin-primary tabular-nums">
            {deepDivePercent}%
          </span>
        </div>
        <div className="mt-1.5 h-1 rounded-full bg-fin-border overflow-hidden">
          <div
            className="h-full rounded-full bg-fin-primary transition-all duration-300"
            style={{ width: `${deepDivePercent}%` }}
          />
        </div>
      </div>
    );
  };

  // Loading state
  if (loading && !insight) {
    return <InsightSkeleton />;
  }

  // Error state (no cached insight available)
  if (error && !insight) {
    return (
      <div className="bg-fin-card rounded-xl border border-fin-border p-4">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-fin-muted text-sm">
            <span>{icon}</span>
            <span>{label}</span>
          </div>
          {renderDeepDiveButton()}
        </div>
        {renderDeepDiveProgress()}
        <p className="text-fin-muted text-xs mt-2">
          AI 分析暂不可用
        </p>
      </div>
    );
  }

  // No insight data
  if (!insight) {
    if (!onDeepDive) return null;
    return (
      <div className="bg-fin-card rounded-xl border border-fin-border p-4">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-fin-muted text-sm">
            <span>{icon}</span>
            <span>{label}</span>
          </div>
          {renderDeepDiveButton()}
        </div>
        {renderDeepDiveProgress()}
        <p className="text-fin-muted text-xs mt-2">
          暂无快速评分，可直接触发 Agent 深挖。
        </p>
      </div>
    );
  }

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
            <CardInfoTip content="快速评分：规则 + 单次 LLM 对实时数据打分（非自主 Agent，无多轮推理/工具调用）。点「深挖」可触发真正的多 Agent 深度分析" />
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
            <span className="text-2xs text-fin-muted bg-fin-border/30 px-1.5 py-0.5 rounded">
              {insight.model_generated ? '快速评分' : '规则评分'}
            </span>
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
        {renderDeepDiveButton()}
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

      {renderDeepDiveProgress()}

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

      {/* Footer: source + confidence + as_of + staleness（P2-4: 置信度与数据时效默认可见） */}
      <div className="flex items-center justify-between mt-3 pt-2 border-t border-fin-border/30">
        <div className="flex items-center gap-1.5">
          <SourceTrustBadge modelGenerated={insight.model_generated} degraded={stale || Boolean(error)} />
          <span className="text-2xs text-fin-muted">
            {insight.model_generated ? '快速评分 (LLM)' : '规则评分'}
          </span>
          {typeof insight.confidence === 'number' && (
            <span className={`text-2xs font-medium ${confidenceColorClass(insight.confidence)}`}>
              置信度 {Math.round(insight.confidence * 100)}%
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {insight.as_of && formatAsOf(insight.as_of) && (
            <span className="text-2xs text-fin-muted">
              数据时点 {formatAsOf(insight.as_of)}
            </span>
          )}
          {stale && (
            <span className="text-2xs text-fin-muted flex items-center gap-1">
              <span className="opacity-60">🕐</span>
              数据可能已过期
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

export default AiInsightCard;
