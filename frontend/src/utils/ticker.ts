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

/** 自动识别时排除的常见英文词和金融缩写。 */
export const TICKER_STOPWORDS = new Set([
  'A', 'I', 'AM', 'PM', 'US', 'UK', 'AI', 'CEO', 'IPO', 'ETF', 'VS',
  'PE', 'EPS', 'MACD', 'RSI', 'KDJ', 'GDP', 'CPI', 'PPI', 'FOMC',
  'WITH', 'VIEW', 'FROM', 'FOR', 'OVER', 'NEWS', 'WHAT', 'WHEN', 'WHERE',
  'WHY', 'THIS', 'THAT', 'THE', 'AND', 'ARE', 'WAS', 'WERE',
]);

export const MAX_AUTO_CHART_TICKERS = 3;
export const TICKER_PATTERN = /^[A-Z0-9^][A-Z0-9.^=-]{0,19}$/;

// ==================== 工具函数 ====================

/** 规范化 ticker token：去空格、转大写、只保留字母数字和 .-_ */
export function normalizeTickerToken(value: string): string {
  return value.trim().toUpperCase().replace(/[^A-Z0-9.\-_]/g, '');
}

/** 按来源优先级合并 ticker 候选，去重、过滤停用词并限制数量。 */
export function mergeTickerCandidates(...sources: Array<string[] | undefined>): string[] {
  const merged: string[] = [];
  const seen = new Set<string>();
  for (const source of sources) {
    for (const raw of source ?? []) {
      const ticker = String(raw || '').trim().toUpperCase();
      if (!ticker || seen.has(ticker)) continue;
      if (TICKER_STOPWORDS.has(ticker) || !TICKER_PATTERN.test(ticker)) continue;
      seen.add(ticker);
      merged.push(ticker);
      if (merged.length >= MAX_AUTO_CHART_TICKERS) return merged;
    }
  }
  return merged;
}

/** 从自然语言中提取指数、市场后缀、加密货币、期货和显式大写 ticker。 */
export function extractTickers(text: string): string[] {
  if (!text || !text.trim()) return [];

  const candidates: string[] = [];
  const addTicker = (raw: string) => candidates.push(String(raw || '').trim().toUpperCase());

  for (const match of text.matchAll(/\^([A-Za-z]{1,8})\b/g)) addTicker(`^${match[1]}`);
  for (const match of text.matchAll(/\b(\d{5,6}\.(?:SS|SZ|BJ|HK))\b/gi)) addTicker(match[1]);
  for (const match of text.matchAll(/\b([A-Za-z]{1,8}-[A-Za-z]{2,5})\b/g)) addTicker(match[1]);
  for (const match of text.matchAll(/\b([A-Za-z]{1,4}=F)\b/g)) addTicker(match[1]);
  for (const match of text.matchAll(/\$([A-Za-z]{1,6})\b/g)) addTicker(match[1]);
  for (const match of text.matchAll(/\b([A-Za-z]{1,6}[.-][A-Za-z]{1,4})\b/g)) addTicker(match[1]);

  // 保留 ChatList 原有的单字母 ticker 支持；停用词会过滤 A / I 等常见误报。
  for (const match of text.matchAll(/\b([A-Za-z]{1,6})\b/g)) {
    const token = match[1];
    if (token === token.toUpperCase()) addTicker(token);
  }

  return mergeTickerCandidates(candidates);
}

export function extractTicker(text: string): string | null {
  return extractTickers(text)[0] ?? null;
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
