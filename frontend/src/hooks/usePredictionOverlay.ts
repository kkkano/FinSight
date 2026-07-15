import { useEffect, useState } from 'react';
import { validate as isUuid } from 'uuid';

import { apiClient } from '../api/client';
import type { LatestPredictionApiResult } from '../api/domains/predictions';
import {
  normalizePredictionOverlay,
  type PredictionOverlay,
} from '../types/chartPrediction';

export type PredictionOverlayLoadState =
  | { status: 'idle' | 'loading' | 'not_found' | 'invalid_explicit_id' | 'unavailable' | 'symbol_mismatch'; overlay: null }
  | { status: 'ready'; overlay: PredictionOverlay };

interface PredictionOverlayLoaders {
  getById: (predictionId: string, signal?: AbortSignal) => Promise<unknown>;
  getLatest: (symbol: string, signal?: AbortSignal) => Promise<LatestPredictionApiResult>;
}

const SYMBOL_PATTERN = /^(?=.{1,32}$)(?:\^[A-Z0-9][A-Z0-9.-]*|[A-Z0-9][A-Z0-9.-]*(?:=[A-Z])?)$/;

export function normalizePredictionRouteSymbol(value: string | undefined): string {
  const normalized = String(value ?? '').trim().toUpperCase();
  return SYMBOL_PATTERN.test(normalized) ? normalized : '';
}

function parseOverlay(payload: unknown, expectedSymbol: string): PredictionOverlayLoadState {
  const parsed = normalizePredictionOverlay(payload);
  if (!parsed) return { status: 'unavailable', overlay: null };
  if (parsed.symbol !== expectedSymbol) return { status: 'symbol_mismatch', overlay: null };
  return { status: 'ready', overlay: parsed };
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
    if (!isUuid(explicitId)) return { status: 'invalid_explicit_id', overlay: null };
    try {
      return parseOverlay(await loaders.getById(explicitId, signal), normalizedSymbol);
    } catch {
      return { status: 'unavailable', overlay: null };
    }
  }

  try {
    const result = await loaders.getLatest(normalizedSymbol, signal);
    return result.status === 'not_found'
      ? { status: 'not_found', overlay: null }
      : parseOverlay(result.payload, normalizedSymbol);
  } catch {
    return { status: 'unavailable', overlay: null };
  }
}

export function usePredictionOverlay(
  symbol: string | undefined,
  explicitPredictionId: string | null | undefined,
  enabled: boolean = true,
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
      },
      controller.signal,
    ).then((next) => {
      if (current && !controller.signal.aborted) setState(next);
    });

    return () => {
      current = false;
      controller.abort();
    };
  }, [enabled, explicitPredictionId, symbol]);

  return state;
}
