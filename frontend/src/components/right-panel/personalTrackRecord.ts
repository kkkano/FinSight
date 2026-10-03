import { apiClient } from '../../api/client';
import type { PredictionHistoryItem } from '../../api/domains/predictions';

export const PERSONAL_PAGE_SIZE = 20;

export const PERSONAL_OUTCOME_LABELS: Record<string, string> = {
  waiting: '等待入场', open: '进行中', triggered: '已触发', invalidated: '已失效',
  hit_target: '目标达成', hit_stop: '止损触发', held_range: '区间成立',
  broke_range: '区间突破', data_pending: '等待行情',
};

export function formatPersonalTime(value: string | null | undefined): string {
  if (!value) return '--';
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return '--';
  return date.toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
}

export function formatPersonalPrice(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(2) : '--';
}

export async function loadPersonalPredictionPage(
  params: { symbol?: string; direction?: 'long' | 'short' | 'neutral'; offset: number },
  signal?: AbortSignal,
  readHistory = apiClient.getPredictionHistory,
): Promise<{ items: PredictionHistoryItem[]; hasMore: boolean }> {
  // 多读一条判断是否还有下一页，不把 90 天统计当作全部历史总数。
  const history = await readHistory({ ...params, limit: PERSONAL_PAGE_SIZE + 1 }, signal);
  return { items: history.items.slice(0, PERSONAL_PAGE_SIZE), hasMore: history.items.length > PERSONAL_PAGE_SIZE };
}
