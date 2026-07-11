/**
 * chatChartIntent.ts —— ChatInput 图表意图判断的纯函数
 *
 * 从 ChatInput.tsx 抽出，满足 react-refresh/only-export-components
 * （组件文件只导出组件，纯函数单独成文件，便于单测）。
 */

// 兼容旧测试/调用入口；实现已统一归入 utils/chartIntent。
export { shouldUseSmartChartData } from '../utils/chartIntent';
