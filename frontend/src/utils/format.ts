/**
 * 通用格式化工具函数。
 *
 * 统一项目中所有货币 / 数字格式化逻辑，避免各组件各自维护重复实现。
 */

/**
 * 将数值格式化为带 $ 前缀的简写货币字符串。
 *
 * - null / undefined / NaN  → '--'
 * - >= 1B                   → $x.xxB
 * - >= 1M                   → $x.xxM
 * - >= 1K                   → $x.xxK
 * - < 1K                    → $x.xx
 *
 * 负数会保留负号。
 */
export function formatCurrency(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';

  const abs = Math.abs(value);
  const sign = value < 0 ? '-' : '';

  if (abs >= 1_000_000_000) return `${sign}$${(abs / 1_000_000_000).toFixed(2)}B`;
  if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `${sign}$${(abs / 1_000).toFixed(2)}K`;
  return `${sign}$${abs.toFixed(2)}`;
}
