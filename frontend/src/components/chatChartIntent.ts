/**
 * chatChartIntent.ts —— ChatInput 图表意图判断的纯函数
 *
 * 从 ChatInput.tsx 抽出，满足 react-refresh/only-export-components
 * （组件文件只导出组件，纯函数单独成文件，便于单测）。
 */

// SmartChart 数据路径：pie/bar 等非 kline 图表，数据来自 /api/chart/data。
// InlineChart 只有 K 线数据源，画不了这些；但 SmartChart 支持，只要能拿到 {labels, values}。
const SMARTCHART_DATA_TYPES = new Set(['pie', 'bar']);
const SMARTCHART_DATA_KINDS = new Set(['composition', 'comparison']);

// 纯函数：判断某 (chartType, dataKind) 是否应走 SmartChart 数据路径。
// 提取为纯函数便于单测（ChatInput 整体依赖 store/SSE，难以直接测）。
export const shouldUseSmartChartData = (
  chartType: string | null,
  dataKind: string | null,
): boolean => {
  if (!chartType || !dataKind) return false;
  return SMARTCHART_DATA_TYPES.has(chartType) && SMARTCHART_DATA_KINDS.has(dataKind);
};
