/**
 * Ticker 标识符规范化与等价比较
 *
 * 处理不同数据源中 ticker 符号的差异（如 GOOG/GOOGL、BRK.B/BRK-B），
 * 提供统一的规范化和等价判定逻辑。
 */

// ==================== 别名组常量 ====================

/** 已知的 ticker 别名组：同一家公司在不同交易所/数据源中的不同表示 */
export const aliasGroups: readonly string[][] = [
  ['GOOG', 'GOOGL'],
  ['BRK.B', 'BRK-B'],
  ['BRKB', 'BRK-B', 'BRK.B'],
];

// ==================== 工具函数 ====================

/** 规范化 ticker token：去空格、转大写、只保留字母数字和 .-_ */
export function normalizeTickerToken(value: string): string {
  return value.trim().toUpperCase().replace(/[^A-Z0-9.\-_]/g, '');
}

/** 判断两个 ticker 是否等价（考虑别名组） */
export function isTickerEquivalent(left: string, right: string): boolean {
  const l = normalizeTickerToken(left);
  const r = normalizeTickerToken(right);
  if (!l || !r) return false;
  if (l === r) return true;

  return aliasGroups.some((group) => group.includes(l) && group.includes(r));
}

/** 判断报告标的是否与当前活跃 ticker 对齐（支持复合标签拆分） */
export function isReportTickerAligned(activeTicker: string, reportTickerLabel: string): boolean {
  const active = normalizeTickerToken(activeTicker);
  if (!active) return true;

  const reportLabel = normalizeTickerToken(reportTickerLabel);
  if (!reportLabel) return true;
  if (isTickerEquivalent(active, reportLabel)) return true;

  const tokens = reportTickerLabel
    .toUpperCase()
    .split(/[^A-Z0-9.\-_]+/)
    .map((token) => normalizeTickerToken(token))
    .filter(Boolean);

  return tokens.some((token) => isTickerEquivalent(active, token));
}
