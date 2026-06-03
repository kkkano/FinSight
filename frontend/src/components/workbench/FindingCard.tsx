/**
 * FindingCard.tsx —— 单个「发现」卡片
 *
 * 结构：触发原因标题（带 trigger_type 图标/色彩）+ summary + 时间
 *      + 行动按钮组（actions 数组渲染）+ 状态标记（新发现有圆点）。
 *
 * 交互：
 * - 点击卡片 → 标记 viewed（onView 回调，内部调 patchFindingStatus）
 * - 行动按钮行为：
 *   - type === 'full_report' → 跳转 Chat 并带 ticker（onNavigateToChat 回调）
 *   - type === 'rebalance'   → 滚动联动到调仓卡片（onNavigateToRebalance 回调）
 *   - 其他类型 → 显示但 disabled + tooltip "Phase 2 开放"
 */
import { Sparkles } from 'lucide-react';
import { useState } from 'react';

import {
  extractMarketSession,
  type AgentAnalysis,
  type Finding,
} from '../../types/monitor';
import {
  formatConfidence,
  isActionEnabled,
  resolveActionTarget,
  resolveAgentLabel,
  resolveSessionBadge,
  resolveTriggerVisual,
} from './findingCardHelpers';

interface FindingCardProps {
  finding: Finding;
  /** 点击卡片标记已读 */
  onView?: (finding: Finding) => void;
  /** 行动按钮：跳转 Chat 深挖（带 ticker） */
  onNavigateToChat?: (ticker: string) => void;
  /** 行动按钮：联动到调仓卡片（滚动 + 高亮） */
  onNavigateToRebalance?: () => void;
}

/** 格式化相对时间（简化版，避免引入额外依赖） */
function formatRelativeTime(iso: string): string {
  const ts = new Date(iso).getTime();
  if (Number.isNaN(ts)) return '';
  const diffMs = Date.now() - ts;
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return '刚刚';
  if (diffMin < 60) return `${diffMin} 分钟前`;
  const diffHour = Math.floor(diffMin / 60);
  if (diffHour < 24) return `${diffHour} 小时前`;
  const diffDay = Math.floor(diffHour / 24);
  return `${diffDay} 天前`;
}

/**
 * AI 分析区块（Phase 2）：agent badge + summary（默认折叠 4 行）+ 置信度 + 数据来源 tag。
 * summary 超过约 4 行时提供「展开全部 / 收起」切换。
 */
function AgentAnalysisBlock({ analysis }: { analysis: AgentAnalysis }) {
  const [expanded, setExpanded] = useState(false);
  const summary = analysis.summary?.trim() ?? '';
  // 用字符长度粗略判断是否可能超 4 行（避免依赖布局测量）
  const isLong = summary.length > 120;

  return (
    <div
      data-testid="finding-agent-analysis"
      className="mt-3 rounded-lg border border-fin-border/60 bg-fin-bg/40 px-3 py-2.5"
      onClick={(e) => e.stopPropagation()}
    >
      <div className="flex items-center gap-2 flex-wrap">
        <span className="inline-flex items-center gap-1 text-fin-primary">
          <Sparkles size={13} />
          <span className="text-2xs font-semibold">AI 分析</span>
        </span>
        <span className="px-1.5 py-0.5 rounded text-2xs font-medium bg-fin-primary/10 text-fin-primary">
          {resolveAgentLabel(analysis.agent)}
        </span>
        <span
          data-testid="finding-agent-confidence"
          className="text-2xs text-fin-muted"
          title="分析置信度"
        >
          置信度 {formatConfidence(analysis.confidence)}
        </span>
      </div>

      {summary && (
        <p
          data-testid="finding-agent-summary"
          className={`mt-1.5 text-xs text-fin-text-secondary leading-relaxed whitespace-pre-line ${
            expanded ? '' : 'line-clamp-4'
          }`}
        >
          {summary}
        </p>
      )}

      {isLong && (
        <button
          type="button"
          data-testid="finding-agent-toggle"
          onClick={() => setExpanded((v) => !v)}
          className="mt-1 text-2xs font-medium text-fin-primary hover:underline"
        >
          {expanded ? '收起' : '展开全部'}
        </button>
      )}

      {analysis.data_sources.length > 0 && (
        <div className="mt-2 flex items-center gap-1 flex-wrap">
          {analysis.data_sources.map((src, idx) => (
            <span
              key={`${src}-${idx}`}
              data-testid="finding-agent-source"
              className="px-1.5 py-0.5 rounded text-2xs text-fin-muted bg-fin-border/30"
            >
              {src}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export function FindingCard({
  finding,
  onView,
  onNavigateToChat,
  onNavigateToRebalance,
}: FindingCardProps) {
  const visual = resolveTriggerVisual(finding.trigger_type, finding.trigger_detail);
  const { Icon } = visual;
  const isNew = finding.status === 'new';
  // 交易时段 badge（盘前/盘后才显示，盘中/闭市/缺失返回 null）
  const sessionBadge = resolveSessionBadge(extractMarketSession(finding.trigger_detail));

  const handleCardClick = () => {
    // 仅未读时触发标记，避免重复请求
    if (isNew) onView?.(finding);
  };

  const handleActionClick = (action: Finding['actions'][number]) => {
    const target = resolveActionTarget(action, finding.target);
    switch (target.kind) {
      case 'rebalance':
        onNavigateToRebalance?.();
        break;
      case 'chat':
        onNavigateToChat?.(target.ticker);
        break;
      default:
        break; // 'none'：不可点击 / 无具体标的
    }
  };

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={handleCardClick}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          handleCardClick();
        }
      }}
      data-testid="finding-card"
      data-status={finding.status}
      className={`relative text-left w-full rounded-xl border bg-fin-card px-4 py-3 transition-colors cursor-pointer ${
        isNew
          ? 'border-fin-primary/40 hover:border-fin-primary/60'
          : 'border-fin-border hover:border-fin-border'
      }`}
    >
      {/* 头部：图标 + 标题 + 类型角标 + 未读圆点 */}
      <div className="flex items-start gap-2.5">
        <span className={`mt-0.5 shrink-0 ${visual.accentClass}`}>
          <Icon size={16} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-semibold text-fin-text">{finding.title}</span>
            <span className={`shrink-0 px-1.5 py-0.5 rounded text-2xs font-medium ${visual.badgeClass}`}>
              {visual.label}
            </span>
            {sessionBadge && (
              <span
                data-testid="finding-session-badge"
                className={`shrink-0 px-1.5 py-0.5 rounded text-2xs font-semibold ${sessionBadge.className}`}
                title="交易时段"
              >
                {sessionBadge.label}
              </span>
            )}
            {isNew && (
              <span
                data-testid="finding-new-dot"
                className="shrink-0 inline-flex h-1.5 w-1.5 rounded-full bg-fin-primary"
                title="新发现"
              />
            )}
          </div>
          <p className="mt-1 text-xs text-fin-text-secondary leading-relaxed">{finding.summary}</p>
          <div className="mt-1 text-2xs text-fin-muted">
            {finding.target !== 'PORTFOLIO' && (
              <span className="mr-2 font-medium text-fin-muted">{finding.target}</span>
            )}
            <span>{formatRelativeTime(finding.created_at)}</span>
          </div>
        </div>
      </div>

      {/* AI 分析区块（Phase 2，agent_analysis 存在时渲染） */}
      {finding.agent_analysis && <AgentAnalysisBlock analysis={finding.agent_analysis} />}

      {/* 行动按钮组 */}
      {finding.actions.length > 0 && (
        <div className="mt-3 flex items-center gap-2 flex-wrap" onClick={(e) => e.stopPropagation()}>
          {finding.actions.map((action, idx) => {
            const enabled = isActionEnabled(action.type);
            return (
              <button
                key={`${action.type}-${idx}`}
                type="button"
                disabled={!enabled}
                onClick={() => handleActionClick(action)}
                title={enabled ? action.label : 'Phase 2 开放'}
                data-testid={`finding-action-${action.type}`}
                className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-colors ${
                  enabled
                    ? 'bg-fin-primary/10 text-fin-primary hover:bg-fin-primary/20'
                    : 'border border-fin-border text-fin-muted opacity-60 cursor-not-allowed'
                }`}
              >
                {action.label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default FindingCard;
