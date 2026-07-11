import { api } from '../http';
import type * as Contracts from '../contracts';

export const dashboardApi = {
/**
   * Fetch personalized daily tasks from ``GET /api/tasks/daily``.
   *
   * Tasks with ``execution_params`` can be directly passed to
   * ``executeAgent()`` for in-place execution.
   */
  async getDailyTasks(params: {
    session_id: string;
    news_count?: number;
    risk_preference?: string;
    watchlist?: string[];
  }): Promise<{
    success: boolean;
    session_id: string;
    risk_preference: string;
    watchlist: string[];
    tasks: Contracts.DailyTask[];
    count: number;
  }> {
    const searchParams = new URLSearchParams();
    searchParams.set('session_id', params.session_id);
    if (params.news_count !== undefined) {
      searchParams.set('news_count', String(params.news_count));
    }
    if (params.risk_preference) {
      searchParams.set('risk_preference', params.risk_preference);
    }
    if (params.watchlist && params.watchlist.length > 0) {
      searchParams.set('watchlist', params.watchlist.join(','));
    }
    const { data } = await api.get(`/api/tasks/daily?${searchParams.toString()}`);
    return data;
  },

// --- Morning Brief (一键晨报) ---
  async generateMorningBrief(params: {
    session_id: string;
    tickers: string[];
  }): Promise<Contracts.MorningBriefResponse> {
    const response = await api.post<Contracts.MorningBriefResponse>('/api/morning-brief/generate', params);
    return response.data;
  },

// --- Dashboard Insights ---
  async getDashboardInsights(
    symbol: string,
    opts?: { force?: boolean; signal?: AbortSignal },
  ): Promise<Contracts.DashboardInsightsResponse> {
    const params: Record<string, string | boolean> = { symbol };
    if (opts?.force) params.force = true;
    const response = await api.get<Contracts.DashboardInsightsResponse>('/api/dashboard/insights', {
      params,
      signal: opts?.signal,
    });
    return response.data;
  },

// --- Monitor（Agent 盯盘中心）---

  /** 获取发现列表 —— GET /api/monitor/findings */
  async getFindings(
    sessionId: string,
    status?: Contracts.FindingStatus,
    limit = 50,
  ): Promise<Contracts.FindingsResponse> {
    const response = await api.get<Contracts.FindingsResponse>('/api/monitor/findings', {
      params: { session_id: sessionId, status, limit },
    });
    return response.data;
  },

/** 更新发现状态（标记已读 / 已行动）—— PATCH /api/monitor/findings/{id} */
  async patchFindingStatus(
    sessionId: string,
    findingId: string,
    status: Contracts.FindingStatus,
  ): Promise<{ success: boolean }> {
    const response = await api.patch(
      `/api/monitor/findings/${encodeURIComponent(findingId)}`,
      { status },
      { params: { session_id: sessionId } },
    );
    return response.data;
  }
};
