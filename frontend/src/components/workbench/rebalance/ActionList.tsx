/**
 * ActionList -- 调仓操作列表，支持逐条接受/拒绝。
 *
 * 列: 展开箭头 / ticker / 操作 badge / 当前 -> 目标权重 / 变动 / 优先级 / 决策按钮
 * 操作颜色: buy=green, sell=red, reduce=orange, increase=cyan, hold=gray
 * 展开行显示完整理由和引用来源。
 */
import { useState, useCallback } from 'react';
import { ChevronDown, ChevronRight, Check, X, RotateCcw } from 'lucide-react';

import { Badge } from '../../ui/Badge.tsx';
import { EvidenceLinks } from './EvidenceLinks.tsx';
import type { RebalanceAction, ActionType } from '../../../types/dashboard.ts';
import type { ActionDecision, ActionDecisionMap } from '../../../hooks/useRebalanceWorkflow.ts';

interface ActionListProps {
  actions: RebalanceAction[];
  decisions?: ActionDecisionMap;
  onSetDecision?: (ticker: string, decision: ActionDecision) => void;
}

/* ---- 操作类型视觉配置 ---- */

interface ActionStyle {
  label: string;
  textClass: string;
  bgClass: string;
}

const ACTION_STYLES: Record<ActionType, ActionStyle> = {
  buy: { label: '买入', textClass: 'text-emerald-600 dark:text-emerald-400', bgClass: 'bg-emerald-500/10' },
  sell: { label: '卖出', textClass: 'text-red-500 dark:text-red-400', bgClass: 'bg-red-500/10' },
  reduce: { label: '减持', textClass: 'text-orange-500 dark:text-orange-400', bgClass: 'bg-orange-500/10' },
  increase: { label: '增持', textClass: 'text-cyan-500 dark:text-cyan-400', bgClass: 'bg-cyan-500/10' },
  hold: { label: '持有', textClass: 'text-fin-muted', bgClass: 'bg-fin-bg-secondary' },
};

function formatWeight(value: number): string {
  return `${value.toFixed(1)}%`;
}

function formatDelta(value: number): string {
  const pct = value.toFixed(1);
  return value >= 0 ? `+${pct}%` : `${pct}%`;
}

export function ActionList({ actions, decisions, onSetDecision }: ActionListProps) {
  const [expandedTicker, setExpandedTicker] = useState<string | null>(null);

  const toggleExpand = useCallback((ticker: string) => {
    setExpandedTicker((prev) => (prev === ticker ? null : ticker));
  }, []);

  if (actions.length === 0) {
    return (
      <p className="text-sm text-fin-muted py-4 text-center">
        暂无调仓操作建议
      </p>
    );
  }

  // 按优先级升序排列（优先级数字越小越靠前）
  const sorted = [...actions].sort((a, b) => a.priority - b.priority);
  const hasWorkflow = Boolean(decisions && onSetDecision);

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-fin-border text-fin-muted">
            <th className="text-left py-2 px-2 font-medium w-6" />
            <th className="text-left py-2 px-2 font-medium">代码</th>
            <th className="text-left py-2 px-2 font-medium">操作</th>
            <th className="text-right py-2 px-2 font-medium">当前</th>
            <th className="text-center py-2 px-1 font-medium" />
            <th className="text-right py-2 px-2 font-medium">目标</th>
            <th className="text-right py-2 px-2 font-medium">变动</th>
            <th className="text-center py-2 px-2 font-medium">优先级</th>
            {hasWorkflow && (
              <th className="text-center py-2 px-2 font-medium">决策</th>
            )}
          </tr>
        </thead>
        <tbody>
          {sorted.map((action) => {
            const style = ACTION_STYLES[action.action];
            const isExpanded = expandedTicker === action.ticker;
            const decision = decisions?.[action.ticker] ?? 'pending';

            return (
              <ActionRow
                key={action.ticker}
                action={action}
                style={style}
                isExpanded={isExpanded}
                onToggle={toggleExpand}
                decision={decision}
                hasWorkflow={hasWorkflow}
                onSetDecision={onSetDecision}
              />
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/* ---- 操作行组件 ---- */

interface ActionRowProps {
  action: RebalanceAction;
  style: ActionStyle;
  isExpanded: boolean;
  onToggle: (ticker: string) => void;
  decision: ActionDecision;
  hasWorkflow: boolean;
  onSetDecision?: (ticker: string, decision: ActionDecision) => void;
}

function ActionRow({
  action,
  style,
  isExpanded,
  onToggle,
  decision,
  hasWorkflow,
  onSetDecision,
}: ActionRowProps) {
  const deltaClass = action.delta_weight >= 0
    ? 'text-emerald-500'
    : 'text-red-400';

  const rowOpacity = decision === 'rejected' ? 'opacity-40' : '';
  const colSpanCount = hasWorkflow ? 9 : 8;

  return (
    <>
      <tr
        className={`border-b border-fin-border/50 hover:bg-fin-hover/50 cursor-pointer transition-all ${rowOpacity}`}
        tabIndex={0}
        role="button"
        aria-expanded={isExpanded}
        onClick={() => onToggle(action.ticker)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            onToggle(action.ticker);
          }
        }}
      >
        <td className="py-2 px-2">
          {isExpanded
            ? <ChevronDown size={12} className="text-fin-muted" />
            : <ChevronRight size={12} className="text-fin-muted" />}
        </td>
        <td className="py-2 px-2 font-semibold text-fin-text">{action.ticker}</td>
        <td className="py-2 px-2">
          <Badge className={`${style.bgClass} ${style.textClass}`}>
            {style.label}
          </Badge>
        </td>
        <td className="py-2 px-2 text-right text-fin-text-secondary">
          {formatWeight(action.current_weight)}
        </td>
        <td className="py-2 px-1 text-center text-fin-muted">
          {'\u2192'}
        </td>
        <td className="py-2 px-2 text-right text-fin-text">
          {formatWeight(action.target_weight)}
        </td>
        <td className={`py-2 px-2 text-right font-medium ${deltaClass}`}>
          {formatDelta(action.delta_weight)}
        </td>
        <td className="py-2 px-2 text-center">
          <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-fin-bg-secondary text-fin-text text-2xs font-medium">
            {action.priority}
          </span>
        </td>
        {hasWorkflow && (
          <td className="py-2 px-2 text-center" onClick={(e) => e.stopPropagation()}>
            <DecisionButtons
              ticker={action.ticker}
              decision={decision}
              onSetDecision={onSetDecision}
            />
          </td>
        )}
      </tr>

      {/* 展开详情行 */}
      {isExpanded && (
        <tr className="bg-fin-bg-secondary/50">
          <td colSpan={colSpanCount} className="px-4 py-3">
            <div className="space-y-2">
              <div>
                <span className="text-2xs text-fin-muted font-medium">调仓理由</span>
                <p className="text-xs text-fin-text-secondary mt-0.5 leading-relaxed">
                  {action.reason}
                </p>
              </div>
              <div>
                <span className="text-2xs text-fin-muted font-medium">引用来源</span>
                <div className="mt-0.5">
                  <EvidenceLinks snapshots={action.evidence_snapshots} />
                </div>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

/* ---- 逐条决策按钮组 ---- */

interface DecisionButtonsProps {
  ticker: string;
  decision: ActionDecision;
  onSetDecision?: (ticker: string, decision: ActionDecision) => void;
}

function DecisionButtons({ ticker, decision, onSetDecision }: DecisionButtonsProps) {
  if (!onSetDecision) return null;

  const handleAccept = () => {
    onSetDecision(ticker, decision === 'accepted' ? 'pending' : 'accepted');
  };

  const handleReject = () => {
    onSetDecision(ticker, decision === 'rejected' ? 'pending' : 'rejected');
  };

  const handleReset = () => {
    onSetDecision(ticker, 'pending');
  };

  return (
    <div className="inline-flex items-center gap-1">
      <button
        type="button"
        onClick={handleAccept}
        title="接受"
        className={`p-1 rounded transition-colors ${
          decision === 'accepted'
            ? 'bg-emerald-500/20 text-emerald-500'
            : 'text-fin-muted hover:text-emerald-500 hover:bg-emerald-500/10'
        }`}
      >
        <Check size={12} />
      </button>
      <button
        type="button"
        onClick={handleReject}
        title="拒绝"
        className={`p-1 rounded transition-colors ${
          decision === 'rejected'
            ? 'bg-red-500/20 text-red-400'
            : 'text-fin-muted hover:text-red-400 hover:bg-red-500/10'
        }`}
      >
        <X size={12} />
      </button>
      {decision !== 'pending' && (
        <button
          type="button"
          onClick={handleReset}
          title="重置"
          className="p-1 rounded text-fin-muted hover:text-fin-text hover:bg-fin-hover transition-colors"
        >
          <RotateCcw size={10} />
        </button>
      )}
    </div>
  );
}
