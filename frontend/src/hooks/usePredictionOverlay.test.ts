import { describe, expect, it, vi } from 'vitest';

import { predictionsApi } from '../api/domains/predictions';
import { loadDashboardPredictionOverlay } from './usePredictionOverlay';

const AAPL_PREDICTION = {
  prediction: {
    predictionId: '11111111-1111-4111-8111-111111111111',
    symbol: 'AAPL',
    direction: 'long',
    anchor: { timeframe: '1d', time: '2026-07-10', price: 103 },
    entry: 104,
    status: 'open',
  },
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
    )).resolves.toEqual({ status: 'invalid_explicit_id', overlay: null });
    expect(getById).not.toHaveBeenCalled();
    expect(getLatest).not.toHaveBeenCalled();
  });

  it('loads latest only without an explicit id and rejects symbol mismatch', async () => {
    const getById = vi.fn();
    const getLatest = vi.fn(async () => ({
      status: 'ready' as const,
      payload: { prediction: { ...AAPL_PREDICTION.prediction, symbol: 'MSFT' } },
    }));

    await expect(loadDashboardPredictionOverlay(
      'AAPL',
      null,
      { getById, getLatest },
    )).resolves.toEqual({ status: 'symbol_mismatch', overlay: null });
    expect(getLatest).toHaveBeenCalledWith('AAPL', undefined);
  });
});

describe('latest prediction API', () => {
  it('returns not_found for 204 without parsing an empty body', async () => {
    const json = vi.fn();
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      status: 204,
      ok: true,
      json,
    } as unknown as Response);

    await expect(predictionsApi.getLatestPrediction('AAPL')).resolves.toEqual({ status: 'not_found' });
    expect(json).not.toHaveBeenCalled();
    fetchMock.mockRestore();
  });
});
