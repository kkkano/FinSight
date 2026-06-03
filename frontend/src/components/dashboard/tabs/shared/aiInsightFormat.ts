/**
 * aiInsightFormat.ts —— AiInsightCard 的纯展示格式化工具
 *
 * 从 AiInsightCard.tsx 抽出，满足 react-refresh/only-export-components
 * （组件文件只导出组件，纯函数单独成文件，便于单测）。
 */

/** P2-4: 置信度颜色编码（>=0.8 绿 / 0.5-0.8 黄 / <0.5 红） */
export function confidenceColorClass(confidence: number): string {
  if (confidence >= 0.8) return 'text-fin-success';
  if (confidence >= 0.5) return 'text-fin-warning';
  return 'text-fin-danger';
}

/** P2-4: 数据时点短格式（无效时间返回空字符串） */
export function formatAsOf(asOf: string): string {
  const date = new Date(asOf);
  if (Number.isNaN(date.getTime())) return '';
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  const hours = String(date.getHours()).padStart(2, '0');
  const minutes = String(date.getMinutes()).padStart(2, '0');
  return `${month}-${day} ${hours}:${minutes}`;
}
