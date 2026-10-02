import type { PredictionDirection, PredictionGroup, PredictionRecord } from '../types/predictions';

export const EARLY_SAMPLE_SIZE = 30;

export function formatRatio(value: number | null, digits = 1): string {
  return value === null || !Number.isFinite(value) ? '待核验' : `${(value * 100).toFixed(digits)}%`;
}

export function formatHitRate(value: number | null, n: number): string {
  return n > 0 ? formatRatio(value) : '等待首批结算';
}

export function formatDelta(value: number | null, n: number): string {
  if (n <= 0) return '等待首批结算';
  if (value === null || !Number.isFinite(value)) return '待核验';
  return `${value > 0 ? '+' : ''}${(value * 100).toFixed(1)} 个百分点`;
}

export function formatEtTime(value: string | null): string {
  if (!value) return '暂无';
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return '暂无';
  return `${new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'America/New_York', dateStyle: 'short', timeStyle: 'short',
  }).format(date)} ET`;
}

export function directionLabel(direction: PredictionDirection | string | null): string {
  return ({ up: '上涨', down: '下跌', flat: '横盘' } as Record<string, string>)[direction || ''] || '尚无判断';
}

export function agentLabel(agent: string): string {
  return ({ technical: 'Technical · 技术面', risk: 'Risk · 风险' } as Record<string, string>)[agent] || agent;
}

export function statusLabel(status: string): string {
  return ({
    registered: '待采集', scheduled: '待采集', queued: '待采集', collecting: '采集中', running: '采集中',
    pending: '待结算', settled: '已结算', awaiting_data: '等待行情',
    failed: '预测失败', missed: '错过登记', abstained: '主动弃权',
    interrupted: '中断待恢复', invalid: '数据待核验',
  } as Record<string, string>)[status] || '其他状态';
}

export function predictionLabel(record: PredictionRecord): string {
  if (record.prediction_type === 'direction') return directionLabel(record.direction);
  if (record.event_occurs === null) return '尚无判断';
  return record.event_occurs ? '发生回撤事件' : '不发生回撤事件';
}

// Identity/version ordering is stable and never ranks or filters models by their scores.
export function sortGroups(groups: PredictionGroup[]): PredictionGroup[] {
  return [...groups].sort((left, right) => {
    const leftKey = [left.agent, left.actual_model, left.prompt_version, left.strategy_version, left.scorer_version].join('|');
    const rightKey = [right.agent, right.actual_model, right.prompt_version, right.strategy_version, right.scorer_version].join('|');
    return leftKey.localeCompare(rightKey);
  });
}

export function sortRecentRecords(records: PredictionRecord[]): PredictionRecord[] {
  return [...records].sort((left, right) =>
    right.batch_date.localeCompare(left.batch_date)
    || left.id.localeCompare(right.id));
}
