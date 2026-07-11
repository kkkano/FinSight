import { api } from '../http';
import type * as Contracts from '../contracts';

export const screenerApi = {
// --- Screener ---
  async runScreener(payload: Contracts.ScreenerRunRequest): Promise<Contracts.ScreenerRunResponse> {
    const response = await api.post<Contracts.ScreenerRunResponse>('/api/screener/run', payload);
    return response.data;
  },

async getScreenerFiltersMeta(): Promise<{
    success: boolean;
    markets: string[];
    sort_by: string[];
    sort_order: string[];
    filter_keys: string[];
    source?: string;
  }> {
    const response = await api.get('/api/screener/filters/meta');
    return response.data;
  }
};
