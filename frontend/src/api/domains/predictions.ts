import { buildApiUrl } from '../../config/runtime';
import { buildAuthHeaders } from '../http';

export type LatestPredictionApiResult =
  | { status: 'ready'; payload: unknown }
  | { status: 'not_found' };

export const predictionsApi = {
  /** 只按不可猜测 id 读取服务端已校验的 prediction；鉴权由统一拦截器附加。 */
  async getPrediction(predictionId: string, signal?: AbortSignal): Promise<unknown> {
    const response = await fetch(
      buildApiUrl(`/api/agents/predictions/${encodeURIComponent(predictionId)}`),
      { headers: await buildAuthHeaders(), signal },
    );
    if (!response.ok) throw new Error(`prediction unavailable: ${response.status}`);
    return response.json();
  },

  async getLatestPrediction(symbol: string, signal?: AbortSignal): Promise<LatestPredictionApiResult> {
    const response = await fetch(
      buildApiUrl(`/api/agents/predictions/latest?symbol=${encodeURIComponent(symbol)}`),
      { headers: await buildAuthHeaders(), signal },
    );
    if (response.status === 204) return { status: 'not_found' };
    if (!response.ok) throw new Error(`prediction unavailable: ${response.status}`);
    return { status: 'ready', payload: await response.json() };
  },
};
