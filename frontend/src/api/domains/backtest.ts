import { api } from '../http';
import type * as Contracts from '../contracts';

export const backtestApi = {
// --- Backtest ---
  async runBacktest(payload: Contracts.BacktestRunRequest): Promise<Contracts.BacktestRunResponse> {
    // 回测是同步长任务（非 SSE），显式放宽超时
    const response = await api.post<Contracts.BacktestRunResponse>('/api/backtest/run', payload, { timeout: 120_000 });
    return response.data;
  },

  async prefillBacktestFromReport(reportId: string): Promise<Contracts.BacktestPrefillResponse> {
    const response = await api.post<Contracts.BacktestPrefillResponse>('/api/backtest/prefill-from-report', {
      report_id: reportId,
    });
    return response.data;
  },

  async listBacktestStrategies(): Promise<{
    success: boolean;
    strategies: Array<Record<string, unknown>>;
  }> {
    const response = await api.get('/api/backtest/strategies');
    return response.data;
  }
};
