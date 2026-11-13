/**
 * SourceBadge — 数据来源徽标（08/09 图表真实性治理的落地件）。
 * 所有图表与数据卡片右上角必挂：真实数据标注来源与截至时间；
 * 模型生成且未核实的数据保留 synthetic 提示，不能与真实行情混淆。
 */

import { zh } from '../../locales/zh';

interface SourceBadgeProps {
  /** 数据源名（yfinance / FMP / akshare…）；synthetic 时可省略 */
  source?: string;
  /** 截至时间（YYYY-MM-DD 或 ISO） */
  asOf?: string | null;
  /** 走了降级源 */
  degraded?: boolean;
  /** 模型生成但未经来源核实的数据 */
  synthetic?: boolean;
  className?: string;
}

export function SourceBadge({ source, asOf, degraded, synthetic, className = '' }: SourceBadgeProps) {
  if (synthetic) {
    return (
      <span
        className={`inline-flex items-center gap-1 px-1 rounded border border-t-warning/50 text-2xs font-mono text-t-warning ${className}`.trim()}
        title={zh.data.generatedDescription}
      >
        {zh.data.generatedUnverified}
      </span>
    );
  }
  if (!source && !asOf) return null;
  return (
    <span className={`inline-flex max-w-full flex-wrap items-center gap-x-1 gap-y-0.5 text-xs text-t-text3 ${className}`.trim()}>
      {degraded && <span className="text-t-warning" title="主数据源不可用，已降级">⚠</span>}
      {source && <span>{source}</span>}
      {source && asOf && <span aria-hidden="true">·</span>}
      {asOf && <span className="whitespace-nowrap tabular-nums">{String(asOf).slice(0, 10)}</span>}
    </span>
  );
}
