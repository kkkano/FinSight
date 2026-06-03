import React, { useState } from 'react';
import { ShieldCheck, ShieldAlert, ShieldX } from 'lucide-react';
import type { ReportQuality, ReportQualityReason } from '../../types/index';

/**
 * P2-12 报告质量徽章（轻量版）。
 *
 * 报告的质量数据（grounding rate / 置信度 / 质量门控状态）已在 report.report_quality 里，
 * FactCheckCard 也展示了详细事实核查。本组件补齐最后一块：报告标题区「一眼可见」的质量徽章。
 *
 * - pass → 绿色「✓ 质量验证通过」
 * - warn → 琥珀「⚠ 质量提示 N 项」（点击展开 reasons 列表）
 * - block / soft_blocked → 红色「⚠ 质量门控拦截」
 * - 无 report_quality 数据 → 不渲染
 */

export interface QualityBadgeProps {
  quality?: ReportQuality | null;
}

type QualityState = 'pass' | 'warn' | 'block';

/** 把后端可能出现的多种门控态归一为三态（soft_blocked 视为 block）。 */
const normalizeState = (state?: string): QualityState | null => {
  if (!state) return null;
  const lowered = state.toLowerCase();
  if (lowered === 'pass') return 'pass';
  if (lowered === 'warn') return 'warn';
  if (lowered === 'block' || lowered === 'soft_blocked' || lowered === 'soft_block') return 'block';
  return null;
};

interface BadgeStyle {
  label: string;
  icon: React.ReactNode;
  tone: string;
}

const buildStyle = (state: QualityState, reasonCount: number): BadgeStyle => {
  switch (state) {
    case 'pass':
      return {
        label: '质量验证通过',
        icon: <ShieldCheck size={13} className="shrink-0" />,
        tone:
          'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-900/20 dark:text-emerald-200',
      };
    case 'warn':
      return {
        label: reasonCount > 0 ? `质量提示 ${reasonCount} 项` : '质量提示',
        icon: <ShieldAlert size={13} className="shrink-0" />,
        tone:
          'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/60 dark:bg-amber-900/20 dark:text-amber-200',
      };
    case 'block':
    default:
      return {
        label: '质量门控拦截',
        icon: <ShieldX size={13} className="shrink-0" />,
        tone:
          'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900/60 dark:bg-rose-900/20 dark:text-rose-200',
      };
  }
};

export const QualityBadge: React.FC<QualityBadgeProps> = ({ quality }) => {
  const [expanded, setExpanded] = useState(false);

  const state = normalizeState(quality?.state);
  // 无质量数据 → 不渲染
  if (!quality || !state) return null;

  const reasons: ReportQualityReason[] = Array.isArray(quality.reasons) ? quality.reasons : [];
  const { label, icon, tone } = buildStyle(state, reasons.length);
  const expandable = reasons.length > 0 && state !== 'pass';

  return (
    <div className="inline-flex flex-col gap-1.5">
      <button
        type="button"
        onClick={() => expandable && setExpanded((prev) => !prev)}
        aria-expanded={expandable ? expanded : undefined}
        className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-semibold ${tone} ${
          expandable ? 'cursor-pointer hover:opacity-90 transition' : 'cursor-default'
        }`}
        title={expandable ? '点击查看质量提示详情' : undefined}
      >
        {icon}
        <span>{label}</span>
      </button>

      {expandable && expanded && (
        <ul className="mt-0.5 max-w-md space-y-1 rounded-lg border border-fin-border bg-fin-card px-3 py-2 text-2xs leading-relaxed text-fin-text-secondary">
          {reasons.map((reason, index) => (
            <li key={`${reason.code || 'reason'}-${index}`} className="flex items-start gap-1.5">
              <span
                className={`mt-0.5 inline-block h-1.5 w-1.5 shrink-0 rounded-full ${
                  reason.severity === 'block' ? 'bg-rose-400' : 'bg-amber-400'
                }`}
              />
              <span className="flex-1">{reason.message || reason.code || '质量提示'}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};
