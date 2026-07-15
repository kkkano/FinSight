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

// 将图表数据加入聊天上下文
  async addChartData(ticker: string, summary: string): Promise<Contracts.ApiResponse> {
    const response = await api.post('/api/chat/add-chart-data', {
      ticker,
      summary
    });
    return response.data;
  },

// 智能检测图表类型
  async detectChartType(query: string, ticker?: string): Promise<Contracts.ApiResponse> {
    try {
      const response = await api.post('/api/chart/detect', {
        query,
        ticker
      });
      return response.data;
    } catch {
      // 即使检测失败也不要阻断流程，返回默认值
      return { success: false, should_generate: false };
    }
  },

// 按 data_kind 拉取非 kline 图表数据（pie=营收构成 / bar=同行对比）。
  // 诚实原则：拿不到数据时返回 success=false，前端跳过出图。
  async getChartData(
    ticker: string,
    dataKind: string,
    fields?: string,
  ): Promise<{
    success: boolean;
    data?: { labels: string[]; values: number[]; unit?: string };
    source?: string;
    fallback_reason?: string;
  }> {
    try {
      const response = await api.post('/api/chart/data', {
        ticker,
        data_kind: dataKind,
        fields,
      });
      return response.data;
    } catch {
      // 调用失败不阻断流程，等价于诚实跳过。
      return { success: false, fallback_reason: 'request_failed' };
    }
  },

// --- CN Market ---
  async getCNFundFlow(limit: number = 20): Promise<Contracts.CNMarketListResponse> {
    const response = await api.get<Contracts.CNMarketListResponse>('/api/cn/market/fund-flow', { params: { limit } });
    return response.data;
  },

async getCNNorthbound(limit: number = 20): Promise<Contracts.CNMarketListResponse> {
    const response = await api.get<Contracts.CNMarketListResponse>('/api/cn/market/northbound', { params: { limit } });
    return response.data;
  },

async getCNLimitBoard(limit: number = 20): Promise<Contracts.CNMarketListResponse> {
    const response = await api.get<Contracts.CNMarketListResponse>('/api/cn/market/limit-board', { params: { limit } });
    return response.data;
  },

async getCNLhb(limit: number = 20): Promise<Contracts.CNMarketListResponse> {
    const response = await api.get<Contracts.CNMarketListResponse>('/api/cn/market/lhb', { params: { limit } });
    return response.data;
  },

async getCNConcept(params?: { keyword?: string; limit?: number }): Promise<Contracts.CNMarketListResponse> {
    const response = await api.get<Contracts.CNMarketListResponse>('/api/cn/market/concept', {
      params: { keyword: params?.keyword || '', limit: params?.limit || 20 },
    });
    return response.data;
  }
};
