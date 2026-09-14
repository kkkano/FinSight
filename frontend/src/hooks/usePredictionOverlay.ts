import { useEffect, useState } from 'react';
import { validate as isUuid } from 'uuid';

import { apiClient } from '../api/client';
import {
  toPredictionFailure,
  type LatestPredictionApiResult,
  type PredictionFailure,
  type PredictionResponse,
  type PredictionRunView,
} from '../api/domains/predictions';
import {
  normalizePredictionOverlay,
  type PredictionOverlay,
} from '../types/chartPrediction';

export type PredictionOverlayLoadState =
  | {
      status: 'idle' | 'loading' | 'not_found' | 'invalid_explicit_id' | 'unavailable' | 'symbol_mismatch';
      overlay: null;
      response?: PredictionResponse | null;
      run?: PredictionRunView | null;
      failure?: PredictionFailure | null;
    }
  | {
      status: 'ready';
      overlay: PredictionOverlay;
      response: PredictionResponse;
      run?: PredictionRunView | null;
      failure?: null;
    };

interface PredictionOverlayLoaders {
  getById: (predictionId: string, signal?: AbortSignal) => Promise<PredictionResponse>;
  getLatest: (symbol: string, signal?: AbortSignal) => Promise<LatestPredictionApiResult>;
  getRun?: (runId: string, signal?: AbortSignal) => Promise<PredictionRunView>;
}

const SYMBOL_PATTERN = /^(?=.{1,32}$)(?:\^[A-Z0-9][A-Z0-9.-]*|[A-Z0-9][A-Z0-9.-]*(?:=[A-Z])?)$/;

export function normalizePredictionRouteSymbol(value: string | undefined): string {
  const normalized = String(value ?? '').trim().toUpperCase();
  return SYMBOL_PATTERN.test(normalized) ? normalized : '';
}

function parseOverlay(payload: PredictionResponse, expectedSymbol: string): PredictionOverlayLoadState {
  const parsed = normalizePredictionOverlay(payload);
  if (!parsed) {
    return {
      status: 'unavailable',
      overlay: null,
      response: payload,
      failure: {
        code: 'prediction_validation_failed',
        message: '已保存的 AI 判断无法通过图表合同校验。',
        status: null,
      },
    };
  }
  if (parsed.symbol !== expectedSymbol) {
    return {
      status: 'symbol_mismatch',
      overlay: null,
      response: payload,
      failure: {
        code: 'prediction_symbol_mismatch',
        message: 'AI 判断标的与当前页面不一致，已停止落图。',
        status: null,
      },
    };
  }
  return { status: 'ready', overlay: parsed, response: payload, failure: null };
}

async function attachRun(
  state: PredictionOverlayLoadState,
  loaders: PredictionOverlayLoaders,
  signal?: AbortSignal,
): Promise<PredictionOverlayLoadState> {
  const runId = state.status === 'ready' ? state.response.prediction?.run_id : null;
  if (!runId || !loaders.getRun) return state;
  try {
    return { ...state, run: await loaders.getRun(runId, signal) };
  } catch {
    // Prediction 本身仍可展示；run 元数据读取失败不应关闭 AI 图层。
    return state;
  }
}

export async function loadDashboardPredictionOverlay(
  symbol: string | undefined,
  explicitPredictionId: string | null | undefined,
  loaders: PredictionOverlayLoaders,
  signal?: AbortSignal,
): Promise<PredictionOverlayLoadState> {
  const normalizedSymbol = normalizePredictionRouteSymbol(symbol);
  if (!normalizedSymbol) return { status: 'idle', overlay: null };

  const explicitId = String(explicitPredictionId ?? '').trim();
  if (explicitId) {
    if (!isUuid(explicitId)) {
      return {
        status: 'invalid_explicit_id',
        overlay: null,
        failure: {
          code: 'prediction_not_found',
          message: 'Prediction 链接格式无效。',
          status: null,
        },
      };
    }
    try {
      const state = parseOverlay(await loaders.getById(explicitId, signal), normalizedSymbol);
      return attachRun(state, loaders, signal);
    } catch (error) {
      return { status: 'unavailable', overlay: null, failure: toPredictionFailure(error) };
    }
  }

  try {
    const result = await loaders.getLatest(normalizedSymbol, signal);
    if (result.status === 'not_found') return { status: 'not_found', overlay: null };
    return attachRun(parseOverlay(result.payload, normalizedSymbol), loaders, signal);
  } catch (error) {
    return { status: 'unavailable', overlay: null, failure: toPredictionFailure(error) };
  }
}

export function usePredictionOverlay(
  symbol: string | undefined,
  explicitPredictionId: string | null | undefined,
  enabled: boolean = true,
  refreshKey: number = 0,
): PredictionOverlayLoadState {
  const [state, setState] = useState<PredictionOverlayLoadState>({ status: 'idle', overlay: null });

  useEffect(() => {
    if (!enabled) {
      setState({ status: 'idle', overlay: null });
      return undefined;
    }
    const controller = new AbortController();
    let current = true;
    setState(normalizePredictionRouteSymbol(symbol)
      ? { status: 'loading', overlay: null }
      : { status: 'idle', overlay: null });

    void loadDashboardPredictionOverlay(
      symbol,
      explicitPredictionId,
      {
        getById: apiClient.getPrediction,
        getLatest: apiClient.getLatestPrediction,
        getRun: apiClient.getPredictionRun,
      },
      controller.signal,
    ).then((next) => {
      if (current && !controller.signal.aborted) setState(next);
    });

    return () => {
      current = false;
      controller.abort();
    };
  }, [enabled, explicitPredictionId, refreshKey, symbol]);

  return state;
}
