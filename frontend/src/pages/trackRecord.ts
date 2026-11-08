import type { PredictionDirection, PredictionGroup, PredictionRecord } from '../types/predictions';

export const EARLY_SAMPLE_SIZE = 30;

export function formatRatio(value: number | null, digits = 1): string {
  return value === null || !Number.isFinite(value) ? '暂无' : `${(value * 100).toFixed(digits)}%`;
}

export function formatHitRate(value: number | null, n: number): string {
  return n > 0 ? formatRatio(value) : '等待首批对账';
}

export function formatDelta(value: number | null, n: number): string {
  if (n <= 0) return '等待首批对账';
  if (value === null || !Number.isFinite(value)) return '暂无';
  return `${value > 0 ? '+' : ''}${(value * 100).toFixed(1)} 个百分点`;
}

export function formatEtTime(value: string | null): string {
  if (!value) return '暂无';
  // 对账窗口的日期字段是交易日，不是UTC午夜；不能转换成美东前一天。
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value.replaceAll('-', '/');
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
  return ({ technical: '方向预测', risk: '大跌预警' } as Record<string, string>)[agent] || '研究预测';
}

export function statusLabel(status: string): string {
  return ({
    registered: '待采集', scheduled: '待采集', queued: '待采集', collecting: '采集中', running: '采集中',
    pending: '等待对账', settled: '已对账', awaiting_data: '等待行情后对账',
    failed: '发布失败，不计入', missed: '当天没按时发布，不计入', abstained: '模型这次选择不预测',
    interrupted: '已中断', invalid: '数据异常',
  } as Record<string, string>)[status] || '其他状态';
}

export function predictionLabel(record: PredictionRecord): string {
  if (record.prediction_type === 'direction') return directionLabel(record.direction);
  if (record.event_occurs === null) return '尚无判断';
  return record.event_occurs ? '发出大跌预警' : '未发出大跌预警';
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
