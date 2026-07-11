import { api } from '../http';
import type * as Contracts from '../contracts';

export const portfolioApi = {
// User profile / watchlist
  async getUserProfile(user_id?: string): Promise<Contracts.ApiResponse> {
    const response = await api.get('/api/user/profile', {
      params: user_id ? { user_id } : {},
    });
    return response.data;
  },

async addWatchlist(payload: { user_id?: string; ticker: string }): Promise<Contracts.ApiResponse> {
    const response = await api.post('/api/user/watchlist/add', payload);
    return response.data;
  },

async removeWatchlist(payload: { user_id?: string; ticker: string }): Promise<Contracts.ApiResponse> {
    const response = await api.post('/api/user/watchlist/remove', payload);
    return response.data;
  },

async getAgentPreferences(user_id?: string): Promise<{
    success: boolean;
    user_id?: string;
    preferences?: Contracts.AgentPreferencesPayload;
    error?: string;
  }> {
    const response = await api.get('/api/agents/preferences', {
      params: user_id ? { user_id } : {},
    });
    return response.data;
  },

async updateAgentPreferences(payload: {
    user_id?: string;
    preferences: Contracts.AgentPreferencesPayload;
  }): Promise<{
    success: boolean;
    user_id?: string;
    preferences?: Contracts.AgentPreferencesPayload;
    error?: string;
  }> {
    const response = await api.put('/api/agents/preferences', payload);
    return response.data;
  },

// --- Rebalance ---
  async generateRebalanceSuggestion(params: Record<string, unknown>): Promise<unknown> {
    const response = await api.post('/api/rebalance/suggestions/generate', params);
    return response.data;
  },

async listRebalanceSuggestions(sessionId: string, limit = 10): Promise<unknown> {
    const response = await api.get('/api/rebalance/suggestions', { params: { session_id: sessionId, limit } });
    return response.data;
  },

async patchRebalanceSuggestion(suggestionId: string, body: { status: string }): Promise<unknown> {
    const response = await api.patch(`/api/rebalance/suggestions/${encodeURIComponent(suggestionId)}`, body);
    return response.data;
  },

// --- Portfolio ---
  async getPortfolioSummary(sessionId: string): Promise<Contracts.PortfolioSummaryResponse> {
    const response = await api.get<Contracts.PortfolioSummaryResponse>('/api/portfolio/summary', { params: { session_id: sessionId } });
    return response.data;
  },

  async calculatePortfolioAttribution(
    positions: Contracts.AttributionPositionInput[],
    lookbackDays = 252,
  ): Promise<Contracts.PortfolioAttributionResponse> {
    const response = await api.post<Contracts.PortfolioAttributionResponse>(
      '/api/portfolio/attribution',
      { positions, lookback_days: lookbackDays },
    );
    return response.data;
  },

async syncPortfolioPositions(
    sessionId: string,
    positions: Array<{ ticker: string; shares: number; avg_cost?: number | null }>,
  ): Promise<{ success: boolean; session_id: string; synced_count: number }> {
    const response = await api.post('/api/portfolio/positions', { session_id: sessionId, positions });
    return response.data;
  },

/** 更新单个持仓（股数 / 成本价）—— PUT /api/portfolio/positions/{ticker}?session_id= */
  async updatePortfolioPosition(
    sessionId: string,
    ticker: string,
    shares: number,
    avgCost?: number | null,
  ): Promise<{ success: boolean; session_id: string; position?: Contracts.PortfolioSummaryPosition }> {
    // 注意：后端的 session_id 是 query 参数（不是 body 字段），放错位置会 422
    const response = await api.put(
      `/api/portfolio/positions/${encodeURIComponent(ticker)}`,
      { shares, avg_cost: avgCost ?? null },
      { params: { session_id: sessionId } },
    );
    return response.data;
  },

/** 删除单个持仓 —— DELETE /api/portfolio/positions/{ticker} */
  async deletePortfolioPosition(
    sessionId: string,
    ticker: string,
  ): Promise<{ success: boolean; session_id: string }> {
    const response = await api.delete(`/api/portfolio/positions/${encodeURIComponent(ticker)}`, {
      params: { session_id: sessionId },
    });
    return response.data;
  }
};
