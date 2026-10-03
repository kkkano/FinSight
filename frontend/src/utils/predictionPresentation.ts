import type { PredictionDirection } from '../types/chartPrediction';

const TERMINAL_STATUSES = new Set(['hit_target', 'hit_stop', 'invalidated', 'held_range', 'broke_range']);

export function isTerminalPredictionStatus(status: string | null | undefined): boolean {
  return TERMINAL_STATUSES.has(status || '');
}

export function getPredictionDirectionPresentation(direction: PredictionDirection, status?: string | null) {
  const historical = isTerminalPredictionStatus(status);
  const meanings = {
    long: { label: '上行假设', description: '满足入场条件后预期向上测试目标价；止损价与失效价定义风险边界。' },
    short: { label: '回落假设', description: '满足入场条件后预期向下测试目标价；属于条件性回落判断，不代表当前技术趋势已转空。' },
    neutral: { label: '区间假设', description: '预期价格保持在所列区间；突破边界后假设失效。' },
  } as const;
  const meaning = meanings[direction];
  return { label: historical ? `原判断：${meaning.label}` : `AI ${meaning.label}`, description: meaning.description, historical };
}
