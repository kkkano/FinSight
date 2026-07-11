import type { InsightCard } from '../../../../types/dashboard';

/** 只统计响应中可追溯到真实输入的结构化指标，不拿文案条数冒充数据依据。 */
export function getInsightBasisCount(insight: InsightCard): number {
  if (Array.isArray(insight.key_metrics) && insight.key_metrics.length > 0) {
    return insight.key_metrics.length;
  }
  if (Array.isArray(insight.score_breakdown) && insight.score_breakdown.length > 0) {
    return insight.score_breakdown.length;
  }
  return Object.keys(insight.sub_scores ?? {}).length;
}

export function formatInsightBasis(insight: InsightCard): string {
  const kind = insight.model_generated ? 'AI 评分' : '规则评分';
  return `${kind} · 基于 ${getInsightBasisCount(insight)} 项真实指标 · 置信度 ${Math.round(insight.confidence * 100)}%`;
}
