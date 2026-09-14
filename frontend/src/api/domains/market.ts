import { api } from '../http';
import type * as Contracts from '../contracts';

export const marketApi = {
  async getWatchlist(): Promise<{
    items: Array<{ ticker: string; note: string; added_at: string }>;
  }> {
    const response = await api.get('/api/watchlist');
    return response.data;
  },

  async addWatchlistItem(payload: { ticker: string; note?: string }): Promise<{
    item: { ticker: string; note: string; added_at: string };
  }> {
    const response = await api.post('/api/watchlist', payload);
    return response.data;
  },

  async removeWatchlistItem(ticker: string): Promise<void> {
    await api.delete(`/api/watchlist/${encodeURIComponent(ticker)}`);
  },

// 获取 K 线数据
  async fetchKline(
    ticker: string,
    period: string = '1y',
    interval: string = '1d',
    signal?: AbortSignal,
  ): Promise<Contracts.KlineResponse> {
    const response = await api.get<Contracts.KlineResponse>(`/api/stock/kline/${ticker}`, {
      params: { period, interval },
      signal,
    });
    return response.data;
  },

async fetchStockPrice(ticker: string): Promise<Contracts.MarketDataResponse<Contracts.QuoteData>> {
    const response = await api.get<Contracts.MarketDataResponse<Contracts.QuoteData>>(
      `/api/stock/price/${encodeURIComponent(ticker)}`,
    );
    return response.data;
  },

};
