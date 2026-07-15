import { describe, expect, it, vi } from 'vitest';

import type { PredictionRunView } from '../api/domains/predictions';
import { pollPredictionRun } from './usePredictionGeneration';

function makeRun(
  status: PredictionRunView['status'],
  overrides: Partial<PredictionRunView> = {},
): PredictionRunView {
  return {
    id: '11111111-1111-4111-8111-111111111111',
    symbol: 'AAPL',
    timeframe: '1d',
    status,
    prompt_version: 'prediction-v1',
    provider_attempts: 0,
    prompt_tokens: 0,
    completion_tokens: 0,
    total_tokens: 0,
    latency_ms: 0,
    created_at: '2026-07-15T08:00:00Z',
    updated_at: '2026-07-15T08:00:00Z',
    ...overrides,
  };
}

describe('Prediction 有限轮询', () => {
  it('终态直接返回，不再请求状态接口', async () => {
    const getRun = vi.fn();
    const succeeded = makeRun('succeeded', { prediction_id: 'pred-1' });

    await expect(pollPredictionRun(succeeded, { getRun })).resolves.toBe(succeeded);
    expect(getRun).not.toHaveBeenCalled();
  });

  it('在预算内拿到 succeeded 后立即停止', async () => {
    let now = 0;
    const getRun = vi
      .fn<() => Promise<PredictionRunView>>()
      .mockResolvedValueOnce(makeRun('running'))
      .mockResolvedValueOnce(makeRun('succeeded', { prediction_id: 'pred-1' }));

    const result = await pollPredictionRun(makeRun('queued'), {
      intervalMs: 5,
      budgetMs: 20,
      now: () => now,
      sleep: async (milliseconds) => { now += milliseconds; },
      getRun,
    });

    expect(result.status).toBe('succeeded');
    expect(getRun).toHaveBeenCalledTimes(2);
  });

  it('预算耗尽后返回最后状态，不形成无限 spinner', async () => {
    let now = 0;
    const getRun = vi.fn(async () => makeRun('running'));

    const result = await pollPredictionRun(makeRun('queued'), {
      intervalMs: 5,
      budgetMs: 10,
      now: () => now,
      sleep: async (milliseconds) => { now += milliseconds; },
      getRun,
    });

    expect(result.status).toBe('running');
    expect(getRun).toHaveBeenCalledTimes(2);
  });
});
