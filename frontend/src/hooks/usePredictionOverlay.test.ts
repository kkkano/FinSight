import { describe, expect, it, vi } from 'vitest';

import { predictionsApi, type PredictionResponse } from '../api/domains/predictions';
import { loadDashboardPredictionOverlay } from './usePredictionOverlay';

const AAPL_PREDICTION: PredictionResponse = {
  prediction: {
    prediction_id: '11111111-1111-4111-8111-111111111111',
    run_id: '22222222-2222-4222-8222-222222222222',
    agent: 'prediction_analyst',
    symbol: 'AAPL',
    direction: 'long',
    anchor: { timeframe: '1d', time: '2026-07-10', price: 103 },
    entry: 104,
    stop: 99,
    target1: 110,
    target2: 116,
    confidence: 0.72,
    thesis: '趋势和证据支持偏多判断。',
    scenarios: [],
    source_type: 'ai',
    prompt_version: 'prediction-v1',
    status: 'open',
    created_at: '2026-07-10T08:00:00Z',
    updated_at: '2026-07-10T08:00:00Z',
  },
  outcome: null,
};

describe('dashboard prediction loader', () => {
  it('uses a valid explicit id exclusively and never falls back to latest', async () => {
    const getById = vi.fn(async () => AAPL_PREDICTION);
    const getLatest = vi.fn(async () => ({ status: 'not_found' as const }));

    await expect(loadDashboardPredictionOverlay(
      'aapl',
      '11111111-1111-4111-8111-111111111111',
      { getById, getLatest },
    )).resolves.toMatchObject({ status: 'ready' });
    expect(getById).toHaveBeenCalledOnce();
    expect(getLatest).not.toHaveBeenCalled();
  });

  it('rejects an invalid explicit id without any request or latest fallback', async () => {
    const getById = vi.fn();
    const getLatest = vi.fn();

    await expect(loadDashboardPredictionOverlay(
      'AAPL',
      'not-a-uuid',
      { getById, getLatest },
    )).resolves.toMatchObject({
      status: 'invalid_explicit_id',
      overlay: null,
      failure: { code: 'prediction_not_found' },
    });
    expect(getById).not.toHaveBeenCalled();
    expect(getLatest).not.toHaveBeenCalled();
  });

  it('loads latest only without an explicit id and rejects symbol mismatch', async () => {
    const getById = vi.fn();
    const getLatest = vi.fn(async () => ({
      status: 'ready' as const,
      payload: {
        ...AAPL_PREDICTION,
        prediction: { ...AAPL_PREDICTION.prediction!, symbol: 'MSFT' },
      },
    }));

    await expect(loadDashboardPredictionOverlay(
      'AAPL',
      null,
      { getById, getLatest },
    )).resolves.toMatchObject({
      status: 'symbol_mismatch',
      overlay: null,
      failure: { code: 'prediction_symbol_mismatch' },
    });
    expect(getLatest).toHaveBeenCalledWith('AAPL', undefined);
  });
});

describe('latest prediction API', () => {
  it('returns not_found for the formal 200/null response', async () => {
    const json = vi.fn(async () => ({ prediction: null, outcome: null }));
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      status: 200,
      ok: true,
      json,
    } as unknown as Response);

    await expect(predictionsApi.getLatestPrediction('AAPL')).resolves.toEqual({ status: 'not_found' });
    expect(json).toHaveBeenCalledOnce();
    fetchMock.mockRestore();
  });
});
