import { api } from '../http';
import type * as Contracts from '../contracts';

export const systemApi = {
async getToolCapabilities(params?: {
    market?: string;
    operation?: string;
    analysis_depth?: 'quick' | 'report' | 'deep_research';
    output_mode?: string;
  }): Promise<Contracts.ToolCapabilitiesResponse> {
    const response = await api.get<Contracts.ToolCapabilitiesResponse>('/api/tools/capabilities', {
      params,
    });
    return response.data;
  },

async diagnosticsOrchestrator(): Promise<Contracts.ApiResponse> {
    const response = await api.get('/diagnostics/orchestrator');
    return response.data;
  },

// 健康检查（含子Agent状态）
  async healthCheck(): Promise<Contracts.ApiResponse> {
    const response = await api.get('/health');
    return response.data;
  },

// P2-7: LLM 成本审计（每日趋势 / Top 消耗 / 汇总）
  async getCostAudit(days: number = 7): Promise<Contracts.ApiResponse> {
    const response = await api.get('/cost-audit', { params: { days } });
    return response.data;
  },

async listSkills(query?: string, limit?: number): Promise<{ success: boolean; count: number; items: Array<Record<string, unknown>> }> {
    const response = await api.get('/api/skills', { params: { query, limit } });
    return response.data;
  },

async listAgents(query?: string, limit?: number): Promise<{ success: boolean; count: number; items: Array<Record<string, unknown>> }> {
    const response = await api.get('/api/agents', { params: { query, limit } });
    return response.data;
  }
};
