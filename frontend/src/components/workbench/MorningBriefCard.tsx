import { useCallback, useMemo } from 'react';
import {
  AlertCircle,
  ArrowDown,
  ArrowUp,
  CheckCircle2,
  Loader2,
  Minus,
  Newspaper,
  RefreshCw,
  Sun,
  TrendingDown,
  TrendingUp,
} from 'lucide-react';

import type { MorningBriefData, MorningBriefHighlight } from '../../api/client';
import { Card } from '../ui/Card';

// ==================== 子组件 ====================

/** 情绪指示器徽章 */
function MoodBadge({ mood, label }: { mood: string; label: string }) {
  const style = useMemo(() => {
    switch (mood) {
      case 'bullish':
        return 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30';
      case 'cautiously_optimistic':
        return 'bg-green-500/15 text-green-400 border-green-500/30';
      case 'cautiously_pessimistic':
        return 'bg-orange-500/15 text-orange-400 border-orange-500/30';
      case 'bearish':
        return 'bg-red-500/15 text-red-400 border-red-500/30';
      default:
        return 'bg-fin-border/30 text-fin-muted border-fin-border';
    }
  }, [mood]);

  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 text-2xs font-medium rounded-full border ${style}`}>
      {mood === 'bullish' || mood === 'cautiously_optimistic' ? (
        <TrendingUp className="w-3 h-3" />
      ) : mood === 'bearish' || mood === 'cautiously_pessimistic' ? (
        <TrendingDown className="w-3 h-3" />
      ) : (
        <Minus className="w-3 h-3" />
      )}
      {label}
    </span>
  );
}

/** 涨跌趋势图标 */
function TrendIcon({ trend, pct }: { trend: string; pct: number | null }) {
  if (pct === null) {
    return <Minus className="w-3.5 h-3.5 text-fin-muted" />;
  }
  if (trend === 'strong_up' || trend === 'up') {
    return <ArrowUp className="w-3.5 h-3.5 text-emerald-400" />;
  }
  if (trend === 'strong_down' || trend === 'down') {
    return <ArrowDown className="w-3.5 h-3.5 text-red-400" />;
  }
  return <Minus className="w-3.5 h-3.5 text-fin-muted" />;
}

/** 涨跌幅颜色 */
function pctColorClass(pct: number | null): string {
  if (pct === null) return 'text-fin-muted';
  if (pct > 0) return 'text-emerald-400';
  if (pct < 0) return 'text-red-400';
  return 'text-fin-muted';
}

/** 格式化百分比 */
function formatPct(pct: number | null): string {
  if (pct === null) return '--';
  const sign = pct >= 0 ? '+' : '';
  return `${sign}${pct.toFixed(2)}%`;
}

/** 单个持仓高亮行 */
function HighlightRow({ item }: { item: MorningBriefHighlight }) {
  return (
    <div className="flex items-center gap-3 py-2 px-2 rounded-lg hover:bg-fin-hover/40 transition-colors">
      {/* 趋势图标 */}
      <TrendIcon trend={item.trend} pct={item.price_change_pct} />

      {/* Ticker + 事件 */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-fin-text">{item.ticker}</span>
          {item.price !== null && (
            <span className="text-2xs text-fin-muted">${item.price.toFixed(2)}</span>
          )}
        </div>
        <div className="text-2xs text-fin-text/70 truncate mt-0.5" title={item.key_event}>
          {item.key_event}
        </div>
      </div>

      {/* 涨跌幅 */}
      <span className={`text-xs font-mono font-medium tabular-nums ${pctColorClass(item.price_change_pct)}`}>
        {formatPct(item.price_change_pct)}
      </span>
    </div>
  );
}

/** 操作建议列表 */
function ActionItems({ items }: { items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div className="space-y-1.5 mt-3 pt-3 border-t border-fin-border/50">
      <div className="flex items-center gap-1.5 text-2xs font-medium text-fin-text/80">
        <CheckCircle2 className="w-3 h-3 text-fin-primary" />
        操作建议
      </div>
      {items.map((item, idx) => (
        <div
          key={`action-${idx}`}
          className="flex items-start gap-2 text-2xs text-fin-text/70 pl-1"
        >
          <span className="text-fin-primary mt-0.5 shrink-0">•</span>
          <span>{item}</span>
        </div>
      ))}
    </div>
  );
}

// ==================== 空状态 ====================

function EmptyState({
  loading,
  onGenerate,
}: {
  loading: boolean;
  onGenerate: () => void;
}) {
  return (
    <div className="flex flex-col items-center justify-center py-6 gap-3">
      <Sun className="w-8 h-8 text-fin-primary/60" />
      <div className="text-sm text-fin-muted text-center">
        点击下方按钮，生成今日投资组合晨报
      </div>
      <button
        type="button"
        onClick={onGenerate}
        disabled={loading}
        className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium rounded-lg bg-fin-primary/15 text-fin-primary hover:bg-fin-primary/25 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        {loading ? (
          <Loader2 className="w-4 h-4 animate-spin" />
        ) : (
          <Newspaper className="w-4 h-4" />
        )}
        {loading ? '正在生成...' : '生成晨报'}
      </button>
    </div>
  );
}

// ==================== 错误状态 ====================

function ErrorState({
  message,
  onRetry,
  loading,
}: {
  message: string;
  onRetry: () => void;
  loading: boolean;
}) {
  return (
    <div className="space-y-3">
      <div className="flex items-start gap-2 rounded-lg border border-fin-danger/40 bg-fin-danger/10 px-3 py-2.5">
        <AlertCircle className="w-4 h-4 text-fin-danger shrink-0 mt-0.5" />
        <div className="text-xs text-fin-danger">{message}</div>
      </div>
      <button
        type="button"
        onClick={onRetry}
        disabled={loading}
        className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg border border-fin-border text-fin-text hover:bg-fin-border/20 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        {loading ? (
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
        ) : (
          <RefreshCw className="w-3.5 h-3.5" />
        )}
        重试
      </button>
    </div>
  );
}

// ==================== 晨报内容 ====================

function BriefContent({
  brief,
  onRefresh,
  loading,
}: {
  brief: MorningBriefData;
  onRefresh: () => void;
  loading: boolean;
}) {
  return (
    <div className="space-y-3">
      {/* 摘要 + 情绪 */}
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs text-fin-text/85 leading-relaxed flex-1">
          {brief.summary}
        </p>
        <MoodBadge mood={brief.market_mood} label={brief.market_mood_cn} />
      </div>

      {/* 持仓高亮列表 */}
      {brief.highlights.length > 0 && (
        <div className="space-y-0.5 max-h-64 overflow-y-auto scrollbar-thin">
          {brief.highlights.map((h) => (
            <HighlightRow key={h.ticker} item={h} />
          ))}
        </div>
      )}

      {/* 操作建议 */}
      <ActionItems items={brief.action_items} />

      {/* 底部：时间 + 刷新 */}
      <div className="flex items-center justify-between pt-2 border-t border-fin-border/40">
        <span className="text-2xs text-fin-muted">
          {brief.generated_at
            ? `生成于 ${new Date(brief.generated_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}`
            : brief.date}
        </span>
        <button
          type="button"
          onClick={onRefresh}
          disabled={loading}
          className="flex items-center gap-1 text-2xs text-fin-muted hover:text-fin-primary disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {loading ? (
            <Loader2 className="w-3 h-3 animate-spin" />
          ) : (
            <RefreshCw className="w-3 h-3" />
          )}
          刷新
        </button>
      </div>
    </div>
  );
}

// ==================== 主组件 ====================

interface MorningBriefCardProps {
  /** 晨报数据，由 useMorningBrief hook 提供 */
  brief: MorningBriefData | null;
  /** 加载状态 */
  loading: boolean;
  /** 错误信息 */
  error: string | null;
  /** 触发生成/刷新 */
  onGenerate: (tickers?: string[]) => void;
}

/**
 * 一键晨报卡片 — 显示投资组合每日摘要。
 *
 * 包含三种视图状态：
 * 1. 空状态（未生成）— 显示生成按钮
 * 2. 错误状态 — 显示错误信息和重试按钮
 * 3. 内容状态 — 显示晨报摘要、持仓变动、操作建议
 */
export function MorningBriefCard({ brief, loading, error, onGenerate }: MorningBriefCardProps) {
  const handleGenerate = useCallback(() => {
    onGenerate();
  }, [onGenerate]);

  return (
    <Card className="p-4 space-y-2" data-testid="morning-brief-card">
      {/* 标题栏 */}
      <div className="flex items-center gap-2">
        <Sun className="w-4 h-4 text-amber-400" />
        <span className="text-sm font-semibold text-fin-text">今日晨报</span>
        {brief?.date && (
          <span className="text-2xs text-fin-muted ml-auto">{brief.date}</span>
        )}
      </div>

      {/* 条件渲染内容 */}
      {error && !brief ? (
        <ErrorState message={error} onRetry={handleGenerate} loading={loading} />
      ) : brief ? (
        <BriefContent brief={brief} onRefresh={handleGenerate} loading={loading} />
      ) : (
        <EmptyState loading={loading} onGenerate={handleGenerate} />
      )}
    </Card>
  );
}

export default MorningBriefCard;
