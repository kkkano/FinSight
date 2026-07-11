export function buildScreenerFilterSummary(market: string, sector: string): string {
  const parts = [`市场=${market.trim().toUpperCase() || '未知'}`];
  const normalizedSector = sector.trim();
  if (normalizedSector) parts.push(`行业=${normalizedSector}`);
  return parts.join('，');
}

export function buildScreenerAskAiPrompt(ticker: string, filterSummary: string): string {
  return `分析一下 ${ticker.trim().toUpperCase()}，它在筛选条件“${filterSummary.trim()}”下入选`;
}
