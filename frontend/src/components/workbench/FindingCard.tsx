/**
 * FindingCard.tsx —— 单个「发现」卡片
 *
 * 结构：触发原因标题（带 trigger_type 图标/色彩）+ summary + 时间
 *      + 行动按钮组（actions 数组渲染）+ 状态标记（新发现有圆点）。
 *
 * 交互：
 * - 点击卡片 → 标记 viewed（onView 回调，内部调 patchFindingStatus）
 * - 行动按钮 Phase 1 行为：
 *   - type === 'full_report' → 跳转 Chat 并带 ticker（onNavigateToChat 回调）
 *   - 其他类型 → 显示但 disabled + tooltip "Phase 2 开放"
 */
import {
  AlertTriangle,
  CalendarClock,
  Globe,
  MessageSquareWarning,
  Sparkles,
  TrendingDown,
  TrendingUp,
} from 'lucide-react';
import { useState, type ComponentType } from 'react';

import type { AgentAnalysis, Finding, FindingTriggerType } from '../../types/monitor';

interface FindingCardProps {
  finding: Finding;
  /** 点击卡片标记已读 */
  onView?: (finding: Finding) => void;
  /** 行动按钮：跳转 Chat 深挖（带 ticker） */
  onNavigateToChat?: (ticker: string) => void;
}

/** trigger_type 视觉映射（图标 + 主色 class，仅用 fin-* / Tailwind 调色板） */
interface TriggerVisual {
  Icon: ComponentType<{ size?: number; className?: string }>;
  /** 图标与边框强调色 */
  accentClass: string;
  /** 角标背景色 */
  badgeClass: string;
  /** 中文类型名 */
  label: string;
}

/**
 * 解析触发类型的视觉表现。
 * price_move 涨跌用方向区分（涨绿跌红），集中度黄色警告，其余各有专属配色。
 */
export function resolveTriggerVisual(
  triggerType: FindingTriggerType,
  detail: Record<string, unknown>,
): TriggerVisual {
  switch (triggerType) {
    case 'price_move': {
      const changePct = Number(detail?.change_pct ?? 0);
      const isUp = changePct >= 0;
      return isUp
        ? {
            Icon: TrendingUp,
            accentClass: 'text-fin-success',
            badgeClass: 'bg-fin-success/10 text-fin-success',
            label: '价格异动',
          }
        : {
            Icon: TrendingDown,
            accentClass: 'text-fin-danger',
            badgeClass: 'bg-fin-danger/10 text-fin-danger',
            label: '价格异动',
          };
    }
    case 'concentration':
      return {
        Icon: AlertTriangle,
        accentClass: 'text-fin-warning',
        badgeClass: 'bg-fin-warning/10 text-fin-warning',
        label: '集中度风险',
      };
    case 'sentiment_shift':
      return {
        Icon: MessageSquareWarning,
        accentClass: 'text-fin-primary',
        badgeClass: 'bg-fin-primary/10 text-fin-primary',
        label: '舆情突变',
      };
    case 'earnings_near':
      return {
        Icon: CalendarClock,
        accentClass: 'text-amber-400',
        badgeClass: 'bg-amber-500/10 text-amber-400',
        label: '财报临近',
      };
    case 'macro_event':
      return {
        Icon: Globe,
        accentClass: 'text-sky-400',
        badgeClass: 'bg-sky-500/10 text-sky-400',
        label: '宏观事件',
      };
    default:
      return {
        Icon: AlertTriangle,
        accentClass: 'text-fin-muted',
        badgeClass: 'bg-fin-border/30 text-fin-muted',
        label: '发现',
      };
  }
}

/** 行动按钮 Phase 1 是否可点击：仅 full_report 可用，其余 Phase 2 开放 */
export function isActionEnabled(actionType: string): boolean {
  return actionType === 'full_report';
}

/** agent 标识 → 中文展示名 */
export function resolveAgentLabel(agent: string): string {
  switch (agent) {
    case 'technical_agent':
      return '技术分析';
    case 'risk_agent':
      return '风险评估';
    default:
      return agent || 'AI';
  }
}

/**
 * 置信度展示：number → 百分比字符串；null → "未评估"（诚实原则，不编造数值）。
 * 兼容 0~1 小数与 0~100 整数两种输入。
 */
export function formatConfidence(confidence: number | null): string {
  if (confidence === null || confidence === undefined || Number.isNaN(confidence)) {
    return '未评估';
  }
  const pct = confidence <= 1 ? confidence * 100 : confidence;
  return `${Math.round(pct)}%`;
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

export function FindingCard({ finding, onView, onNavigateToChat }: FindingCardProps) {
  const visual = resolveTriggerVisual(finding.trigger_type, finding.trigger_detail);
  const { Icon } = visual;
  const isNew = finding.status === 'new';

  const handleCardClick = () => {
    // 仅未读时触发标记，避免重复请求
    if (isNew) onView?.(finding);
  };

  const handleActionClick = (action: Finding['actions'][number]) => {
    if (!isActionEnabled(action.type)) return;
    const ticker = action.ticker || finding.target;
    if (ticker && ticker !== 'PORTFOLIO') {
      onNavigateToChat?.(ticker);
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
