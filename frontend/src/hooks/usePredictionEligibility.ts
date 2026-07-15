import { useEffect, useState } from 'react';

import { apiClient } from '../api/client';

export type PredictionEligibility = {
  status: 'idle' | 'checking' | 'trusted' | 'degraded' | 'unavailable';
  provider: string | null;
  asOf: string | null;
  reason: string | null;
};

const IDLE: PredictionEligibility = {
  status: 'idle',
  provider: null,
  asOf: null,
  reason: null,
};

export function usePredictionEligibility(symbol: string): PredictionEligibility {
  const [state, setState] = useState<PredictionEligibility>(IDLE);

  useEffect(() => {
    const normalized = symbol.trim().toUpperCase();
    if (!normalized) {
      setState(IDLE);
      return undefined;
    }

    const controller = new AbortController();
    setState({ status: 'checking', provider: null, asOf: null, reason: null });
    void apiClient.fetchKline(normalized, '1y', '1d', controller.signal)
      .then((response) => {
        if (controller.signal.aborted) return;
        const envelope = response.data;
        const rows = envelope.kline_data ?? envelope.data;
        const hasRows = Array.isArray(rows) && rows.length > 0;
        const base = {
          provider: envelope.provider ?? null,
          asOf: envelope.as_of ?? null,
        };
        if (hasRows && envelope.quality === 'trusted') {
          setState({ status: 'trusted', ...base, reason: null });
          return;
        }
        if (hasRows) {
          setState({
            status: 'degraded',
            ...base,
            reason: '当前只有降级行情，不能作为 AI Prediction 锚点。',
          });
          return;
        }
        setState({
          status: 'unavailable',
          ...base,
          reason: '可信 K 线尚未就绪。',
        });
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setState({
            status: 'unavailable',
            provider: null,
            asOf: null,
            reason: '行情状态检查失败，请刷新后重试。',
          });
        }
      });

    return () => controller.abort();
  }, [symbol]);

  return state;
}
