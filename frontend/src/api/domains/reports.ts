import { api } from '../http';
import type * as Contracts from '../contracts';

export const reportsApi = {
async listReportIndex(params: {
    sessionId: string;
    ticker?: string;
    query?: string;
    dateFrom?: string;
    dateTo?: string;
    tag?: string;
    sourceType?: string;
    favoriteOnly?: boolean;
    includeBlocked?: boolean;
    limit?: number;
  }): Promise<{ success: boolean; session_id: string; items: Contracts.ReportIndexItem[]; count: number }> {
    const response = await api.get('/api/reports/index', {
      params: {
        session_id: params.sessionId,
        ticker: params.ticker,
        query: params.query,
        date_from: params.dateFrom,
        date_to: params.dateTo,
        tag: params.tag,
        source_type: params.sourceType,
        favorite_only: params.favoriteOnly,
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
  }): Promise<{ success: boolean; session_id: string; report: any; citations: any[]; trace_digest: Record<string, any> }> {
    const response = await api.get(`/api/reports/replay/${encodeURIComponent(params.reportId)}`, {
      params: { session_id: params.sessionId, include_blocked: params.includeBlocked },
    });
    return response.data;
  },

async setReportFavorite(params: {
    sessionId: string;
    reportId: string;
    isFavorite: boolean;
  }): Promise<{ success: boolean; session_id: string; report_id: string; is_favorite: boolean }> {
    const response = await api.post(`/api/reports/${encodeURIComponent(params.reportId)}/favorite`, {
      session_id: params.sessionId,
      is_favorite: params.isFavorite,
    });
    return response.data;
  },

// P2-11 报告与实时价差提示：拉实时价并与报告生成时刻对比。
  // report_price 可选，缺失时后端只做「报告时效」判定（report_age_hours >= 24）。
  async checkPriceDrift(params: {
    ticker: string;
    reportPrice?: number | null;
    reportGeneratedAt?: string;
  }): Promise<{
    ticker: string;
    report_price: number | null;
    current_price: number | null;
    drift_pct: number | null;
    report_age_hours: number | null;
    threshold_pct: number;
    significant: boolean;
  }> {
    const response = await api.get('/api/reports/price-drift', {
      params: {
        ticker: params.ticker,
        report_price: params.reportPrice ?? undefined,
        report_generated_at: params.reportGeneratedAt,
      },
    });
    return response.data;
  },

/** Compare two reports — GET /api/reports/compare */
  async compareReports(params: {
    sessionId: string;
    reportId1: string;
    reportId2: string;
    includeBlocked?: boolean;
  }): Promise<{
    report_a: { report_id: string; title?: string | null; generated_at?: string | null };
    report_b: { report_id: string; title?: string | null; generated_at?: string | null };
    diff: {
      confidence_score: { a: number | null; b: number | null; delta: number | null };
      sentiment: { a: string | null; b: string | null; changed: boolean };
      risks: { added: string[]; removed: string[]; unchanged_count: number };
      summary: { a: string | null; b: string | null };
    };
  }> {
    const response = await api.get('/api/reports/compare', {
      params: {
        session_id: params.sessionId,
        id1: params.reportId1,
        id2: params.reportId2,
        include_blocked: params.includeBlocked,
      },
    });
    const raw = response.data;
    return {
      report_a: raw.report_a ?? { report_id: params.reportId1 },
      report_b: raw.report_b ?? { report_id: params.reportId2 },
      diff: raw.diff ?? {
        confidence_score: { a: null, b: null, delta: null },
        sentiment: { a: null, b: null, changed: false },
        risks: { added: [], removed: [], unchanged_count: 0 },
        summary: { a: null, b: null },
      },
    };
  },

// 导出 PDF
  async exportPDF(messages: any[], charts?: any[], title?: string): Promise<Blob> {
    const response = await api.post('/api/export/pdf', {
      messages,
      charts: charts || [],
      title: title || 'FinSight 对话记录'
    }, {
      responseType: 'blob', // 关键：声明返回二进制流
      timeout: 120_000 // PDF 渲染是同步长任务，显式放宽
    });
    return response.data;
  }
};
