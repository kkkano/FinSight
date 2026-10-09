/**
 * chatChartIntent.ts —— ChatInput 图表意图判断的纯函数
 *
 * 从 ChatInput.tsx 抽出，满足 react-refresh/only-export-components
 * （组件文件只导出组件，纯函数单独成文件，便于单测）。
 */

/** Dashboard prediction 深链只读取不可猜测 id，其余查询字段不会进入图表合同。 */
export function getPredictionIdFromSearch(search: string): string | null {
  const params = new URLSearchParams(search);
  const analysis = params.get('analysis')?.trim();
  const raw = (analysis === 'prediction' ? params.get('predictionId')?.trim() || analysis : analysis) || '';
  return raw && raw.length <= 160 ? raw : null;
}

export function buildPredictionDashboardUrl(symbol: string, predictionId: string): string {
  return `/dashboard/${encodeURIComponent(symbol)}?${new URLSearchParams({ analysis: predictionId })}`;
}
