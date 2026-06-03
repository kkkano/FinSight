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

// --- 市场感知格式化（P2-10 A股体验补齐） ---

/**
 * 根据 ticker 后缀推断币种符号。
 *
 * - `.SS` / `.SZ` / `.BJ`（A股，上交所/深交所/北交所）→ `¥`
 * - `.HK`（港股）                                    → `HK$`
 * - 其他（美股等）                                    → `$`
 */
export function currencySymbolForTicker(ticker: string | null | undefined): string {
  const symbol = String(ticker ?? '').trim().toUpperCase();
  if (symbol.endsWith('.SS') || symbol.endsWith('.SZ') || symbol.endsWith('.BJ')) return '¥';
  if (symbol.endsWith('.HK')) return 'HK$';
  return '$';
}

/** 判断 ticker 是否为 A股（上交所/深交所/北交所）。 */
export function isAShareTicker(ticker: string | null | undefined): boolean {
  const symbol = String(ticker ?? '').trim().toUpperCase();
  return symbol.endsWith('.SS') || symbol.endsWith('.SZ') || symbol.endsWith('.BJ');
}

/**
 * 市场感知的价格格式化：A股用 ¥，港股用 HK$，其余用 $。
 *
 * null / undefined / NaN → '--'。保留 2 位小数与千分位。
 */
export function formatPriceForMarket(
  value: number | null | undefined,
  ticker: string | null | undefined,
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  const prefix = currencySymbolForTicker(ticker);
  return `${prefix}${value.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

/**
 * 市场感知的市值格式化。
 *
 * - A股 / 港股：用「万亿 / 亿」（中文计数习惯），如 `¥1.23万亿`、`HK$4500.0亿`
 * - 美股等：用 `T / B / M`，如 `$3.40T`
 *
 * null / undefined / NaN → '--'。
 */
export function formatMarketCapForMarket(
  value: number | null | undefined,
  ticker: string | null | undefined,
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';

  const prefix = currencySymbolForTicker(ticker);
  const cn = prefix === '¥' || prefix === 'HK$';
  const abs = Math.abs(value);
  const sign = value < 0 ? '-' : '';

  if (cn) {
    // 中文计数：1万亿 = 1e12，1亿 = 1e8
    if (abs >= 1e12) return `${sign}${prefix}${(abs / 1e12).toFixed(2)}万亿`;
    if (abs >= 1e8) return `${sign}${prefix}${(abs / 1e8).toFixed(1)}亿`;
    if (abs >= 1e4) return `${sign}${prefix}${(abs / 1e4).toFixed(1)}万`;
    return `${sign}${prefix}${abs.toFixed(2)}`;
  }

  if (abs >= 1e12) return `${sign}${prefix}${(abs / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `${sign}${prefix}${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${sign}${prefix}${(abs / 1e6).toFixed(2)}M`;
  return `${sign}${prefix}${abs.toLocaleString()}`;
}
