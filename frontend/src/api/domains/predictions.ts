import { buildApiUrl } from '../../config/runtime';
import { buildAuthHeaders } from '../http';

export const predictionsApi = {
  /** 只按不可猜测 id 读取服务端已校验的 prediction；鉴权由统一拦截器附加。 */
  async getPrediction(predictionId: string): Promise<unknown> {
    const response = await fetch(
      buildApiUrl(`/api/agents/predictions/${encodeURIComponent(predictionId)}`),
      { headers: await buildAuthHeaders() },
    );
    if (!response.ok) throw new Error(`prediction unavailable: ${response.status}`);
    return response.json();
  },
};
