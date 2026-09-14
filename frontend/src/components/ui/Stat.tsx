/**
 * Stat — 终端风数值展示（08 设计语言）。
 * 标签小写间距 + 等宽数字 + 涨跌语义色（▲▼ 字符，随 A股/国际配色开关）。
 */

interface StatProps {
  label: string;
  value: string | number;
  /** 涨跌变化（如 +2.31 / -1.2%），正负决定配色与箭头；不传则不渲染变化行 */
  change?: number | null;
  /** 变化的展示文本；缺省用 change 数值 + '%' */
  changeText?: string;
  className?: string;
}

export function Stat({ label, value, change, changeText, className = '' }: StatProps) {
  const hasChange = typeof change === 'number' && Number.isFinite(change);
  const isUp = hasChange && (change as number) >= 0;
  return (
    <div className={className}>
      <div className="text-2xs uppercase tracking-wider text-t-text3">{label}</div>
      <div className="num text-lg text-t-text">{value}</div>
      {hasChange && (
        <div className={`num text-xs ${isUp ? 'text-t-up' : 'text-t-down'}`}>
          {isUp ? '▲' : '▼'} {changeText ?? `${Math.abs(change as number).toFixed(2)}%`}
        </div>
      )}
    </div>
  );
}
