/**
 * findingCardHelpers.ts —— FindingCard 的纯函数与视觉解析工具
 *
 * 从 FindingCard.tsx 抽出，满足 react-refresh/only-export-components
 * （组件文件只导出组件，纯函数单独成文件，便于单测）。
 */
import {
  AlertTriangle,
  CalendarClock,
  Globe,
  MessageSquareWarning,
  TrendingDown,
  TrendingUp,
} from 'lucide-react';
import type { ComponentType } from 'react';

import type {
  FindingAction,
  FindingTriggerType,
  MarketSession,
} from '../../types/monitor';

/** trigger_type 视觉映射（图标 + 主色 class，仅用 fin-* / Tailwind 调色板） */
export interface TriggerVisual {
  Icon: ComponentType<{ size?: number; className?: string }>;
  /** 图标与边框强调色 */
  accentClass: string;
  /** 角标背景色 */
  badgeClass: string;
  /** 卡片左侧强调色条背景（视觉锚点，与 accent 同色系） */
  stripeClass: string;
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
            stripeClass: 'bg-fin-success',
            label: '价格异动',
          }
        : {
            Icon: TrendingDown,
            accentClass: 'text-fin-danger',
            badgeClass: 'bg-fin-danger/10 text-fin-danger',
            stripeClass: 'bg-fin-danger',
            label: '价格异动',
          };
    }
    case 'concentration':
      return {
        Icon: AlertTriangle,
        accentClass: 'text-fin-warning',
        badgeClass: 'bg-fin-warning/10 text-fin-warning',
        stripeClass: 'bg-fin-warning',
        label: '集中度风险',
      };
    case 'sentiment_shift':
      return {
        Icon: MessageSquareWarning,
        accentClass: 'text-fin-primary',
        badgeClass: 'bg-fin-primary/10 text-fin-primary',
        stripeClass: 'bg-fin-primary',
        label: '舆情突变',
      };
    case 'earnings_near':
      return {
        Icon: CalendarClock,
        accentClass: 'text-amber-400',
        badgeClass: 'bg-amber-500/10 text-amber-400',
        stripeClass: 'bg-amber-400/70',
        label: '财报临近',
      };
    case 'macro_event':
      return {
        Icon: Globe,
        accentClass: 'text-sky-400',
        badgeClass: 'bg-sky-500/10 text-sky-400',
        stripeClass: 'bg-sky-400/70',
        label: '宏观事件',
      };
    default:
      return {
        Icon: AlertTriangle,
        accentClass: 'text-fin-muted',
        badgeClass: 'bg-fin-border/30 text-fin-muted',
        stripeClass: 'bg-fin-border',
        label: '发现',
      };
  }
}

/**
 * 解析交易时段 badge（纯函数，便于 renderToStaticMarkup 测试）。
 * - pre_market → 醒目橙色「盘前」（傍晚提醒、开盘前决策，对国内用户价值最高）
 * - after_hours → 低调靛蓝「盘后」（不抢眼）
 * - regular / closed / null → 不显示（盘中是常态，无需标注）
 *
 * 配色用 Tailwind 调色板（orange-* / indigo-*），可带 alpha；
 * fin-* hex 变量不能带 alpha，故时段 badge 不用 fin-* token。
 */
export function resolveSessionBadge(
  session: MarketSession | null,
): { label: string; className: string } | null {
  switch (session) {
    case 'pre_market':
      return {
        label: '盘前',
        className: 'bg-orange-500/10 text-orange-500 border border-orange-500/30',
      };
    case 'after_hours':
      return {
        label: '盘后',
        className: 'bg-indigo-500/10 text-indigo-400 border border-indigo-500/20',
      };
    default:
      return null;
  }
}

/**
 * 行动按钮是否可点击。
 * full_report → 跳 Chat 深挖；rebalance → 联动调仓卡片；其余仍为 Phase 2 待开放。
 */
export function isActionEnabled(actionType: string): boolean {
  return actionType === 'full_report' || actionType === 'rebalance';
}

/**
 * 解析一个行动按钮应触发的目标行为（纯函数，便于测试）。
 * - 'none'      → 不可点击 / 无效（Phase 2 待开放，或 PORTFOLIO 级无具体标的）
 * - 'rebalance' → 联动调仓卡片
 * - 'chat'      → 带 ticker 跳 Chat（target 字段给出 ticker）
 */
export type ActionTarget =
  | { kind: 'none' }
  | { kind: 'rebalance' }
  | { kind: 'chat'; ticker: string };

export function resolveActionTarget(
  action: FindingAction,
  fallbackTarget: string,
): ActionTarget {
  if (!isActionEnabled(action.type)) return { kind: 'none' };
  if (action.type === 'rebalance') return { kind: 'rebalance' };
  const ticker = action.ticker || fallbackTarget;
  if (ticker && ticker !== 'PORTFOLIO') return { kind: 'chat', ticker };
  return { kind: 'none' };
}

/** agent 标识 → 中文展示名 */
export function resolveAgentLabel(agent: string): string {
  switch (agent) {
    case 'technical_agent':
      return '技术分析';
    case 'risk_agent':
      return '风险评估';
    case 'news_agent':
      return '舆情分析';
    case 'deep_search_agent':
      return '深度研究';
    case 'macro_agent':
      return '宏观分析';
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
