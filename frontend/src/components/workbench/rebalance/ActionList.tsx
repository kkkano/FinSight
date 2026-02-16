/**
 * ActionList — Table of rebalance actions with expandable detail rows.
 *
 * Columns: ticker / action badge / current -> target weight / delta / priority / reason
 * Action colours: buy=green, sell=red, reduce=orange, increase=cyan, hold=gray
 * Expanding a row reveals the full reason text and evidence links.
 */
import { useState, useCallback } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';

import { Badge } from '../../ui/Badge.tsx';
import { EvidenceLinks } from './EvidenceLinks.tsx';
import type { RebalanceAction, ActionType } from '../../../types/dashboard.ts';

interface ActionListProps {
  actions: RebalanceAction[];
}

/* ---- Action type visual config ---- */

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
  return `${(value * 100).toFixed(1)}%`;
}

function formatDelta(value: number): string {
  const pct = (value * 100).toFixed(1);
  return value >= 0 ? `+${pct}%` : `${pct}%`;
}

export function ActionList({ actions }: ActionListProps) {
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

  // Sort by priority (ascending = highest priority first)
  const sorted = [...actions].sort((a, b) => a.priority - b.priority);

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
          </tr>
        </thead>
        <tbody>
          {sorted.map((action) => {
            const style = ACTION_STYLES[action.action];
            const isExpanded = expandedTicker === action.ticker;

            return (
              <ActionRow
                key={action.ticker}
                action={action}
                style={style}
                isExpanded={isExpanded}
                onToggle={toggleExpand}
              />
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/* ---- Individual action row (extracted for clarity) ---- */

interface ActionRowProps {
  action: RebalanceAction;
  style: ActionStyle;
  isExpanded: boolean;
  onToggle: (ticker: string) => void;
}

function ActionRow({ action, style, isExpanded, onToggle }: ActionRowProps) {
  const deltaClass = action.delta_weight >= 0
    ? 'text-emerald-500'
    : 'text-red-400';

  return (
    <>
      <tr
        className="border-b border-fin-border/50 hover:bg-fin-hover/50 cursor-pointer transition-colors"
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
      </tr>

      {/* Expanded detail row */}
      {isExpanded && (
        <tr className="bg-fin-bg-secondary/50">
          <td colSpan={8} className="px-4 py-3">
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
