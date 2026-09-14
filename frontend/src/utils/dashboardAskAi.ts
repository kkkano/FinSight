const DASHBOARD_TAB_LABELS: Record<string, string> = {
  overview: '综合分析',
  financial: '财务报表',
  technical: '技术面',
  news: '新闻动态',
  research: '深度研究',
  peers: '同行对比',
};

export function getDashboardTabLabel(tab: string | null | undefined): string {
  return DASHBOARD_TAB_LABELS[tab || 'overview'] ?? DASHBOARD_TAB_LABELS.overview;
}

export function buildDashboardAskAiDraft(symbol: string, tab: string | null | undefined): string {
  return `关于 ${symbol.trim().toUpperCase()} 的${getDashboardTabLabel(tab)}，`;
}
