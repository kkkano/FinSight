import { describe, expect, it } from 'vitest';

import type { PortfolioSummaryResponse } from '../../api/contracts';
import { upsertPortfolioSummaryPosition } from './portfolioSummaryCache';


describe('upsertPortfolioSummaryPosition', () => {
  it('持仓股数变化后立即按现价更新市值和组合权重基础', () => {
    const current: PortfolioSummaryResponse = {
      success: true,
      session_id: 'test',
      count: 2,
      total_value: 1000,
      total_cost: 700,
      total_pnl: 300,
      positions: [
        { ticker: 'AAPL', shares: 4, avg_cost: 75, live_price: 100, market_value: 400, cost_basis: 300 },
        { ticker: 'MSFT', shares: 3, avg_cost: 133.33, live_price: 200, market_value: 600, cost_basis: 400 },
      ],
    };

    const next = upsertPortfolioSummaryPosition(current, 'AAPL', 8, 75);

    expect(next?.positions[0].market_value).toBe(800);
    expect(next?.total_value).toBe(1400);
    expect(next?.total_pnl).toBe(400);
  });
});
