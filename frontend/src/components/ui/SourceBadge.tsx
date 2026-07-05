/**
 * SourceBadge — 数据来源徽标（08/09 图表真实性治理的落地件）。
 * 所有图表与数据卡片右上角必挂：真实数据标注来源与截至时间；
 * LLM 生成的示意数据必须 synthetic 亮黄标，禁止与真实数据混淆。
 */

interface SourceBadgeProps {
  /** 数据源名（yfinance / FMP / akshare…）；synthetic 时可省略 */
  source?: string;
  /** 截至时间（YYYY-MM-DD 或 ISO） */
  asOf?: string | null;
  /** 走了降级源 */
  degraded?: boolean;
  /** LLM 生成的示意数据（非真实行情） */
  synthetic?: boolean;
  className?: string;
}

export function SourceBadge({ source, asOf, degraded, synthetic, className = '' }: SourceBadgeProps) {
  if (synthetic) {
    return (
      <span
        className={`inline-flex items-center gap-1 px-1 rounded border border-t-warning/50 text-2xs font-mono text-t-warning ${className}`.trim()}
        title="此图数据由 AI 生成，仅作示意，非真实行情"
      >
        AI示意
      </span>
    );
  }
  if (!source && !asOf) return null;
  return (
    <span className={`inline-flex items-center gap-1 text-2xs font-mono text-t-text3 ${className}`.trim()}>
      {degraded && <span className="text-t-warning" title="主数据源不可用，已降级">⚠</span>}
      {source}
      {source && asOf ? ' · ' : ''}
      {asOf ? String(asOf).slice(0, 10) : ''}
    </span>
  );
}
