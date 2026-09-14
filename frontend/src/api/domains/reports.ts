import { api } from '../http';
import type * as Contracts from '../contracts';

export const reportsApi = {
  async createReportShare(reportId: string): Promise<{ share_url: string }> {
    const response = await api.post(`/api/reports/${encodeURIComponent(reportId)}/share`);
    return response.data;
  },

  async revokeReportShare(reportId: string): Promise<void> {
    await api.delete(`/api/reports/${encodeURIComponent(reportId)}/share`);
  },

  async getSharedReport(token: string): Promise<{ report: Contracts.ReportIR }> {
    const response = await api.get(`/api/reports/shared/${encodeURIComponent(token)}`);
    return response.data;
  },

  async listReportIndex(params: {
    sessionId: string;
    ticker?: string;
    query?: string;
    sourceType?: string;
    includeBlocked?: boolean;
    limit?: number;
  }): Promise<{ session_id: string; items: Contracts.ReportIndexItem[]; count: number }> {
    const response = await api.get('/api/reports/index', {
      params: {
        session_id: params.sessionId,
        ticker: params.ticker,
        query: params.query,
        source_type: params.sourceType,
        include_blocked: params.includeBlocked,
        limit: params.limit,
      },
    });
    return response.data;
  },

  async getReportReplay(params: {
    sessionId: string;
    reportId: string;
    includeBlocked?: boolean;
  }): Promise<{ session_id: string; report: any; citations: any[]; trace_digest: Record<string, any> }> {
    const response = await api.get(`/api/reports/replay/${encodeURIComponent(params.reportId)}`, {
      params: { session_id: params.sessionId, include_blocked: params.includeBlocked },
    });
    return response.data;
  },

};
