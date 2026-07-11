import { describe, expect, it } from 'vitest';

import type { PortfolioSummaryResponse } from '../../api/contracts';
import { buildAttributionPositions } from './attributionUtils';


const summary = (positions: PortfolioSummaryResponse['positions']): PortfolioSummaryResponse => ({
  success: true,
  session_id: 'test',
  positions,
  count: positions.length,
  total_value: positions.reduce((sum, item) => sum + item.market_value, 0),
  total_cost: 0,
  total_pnl: 0,
});


describe('buildAttributionPositions', () => {
  it('按持仓市值生成归一化权重', () => {
    const positions = buildAttributionPositions(summary([
      { ticker: 'AAPL', shares: 2, market_value: 400, cost_basis: 300 },
      { ticker: 'MSFT', shares: 4, market_value: 600, cost_basis: 500 },
    ]));

    expect(positions).toEqual([
      { ticker: 'AAPL', weight: 0.4 },
      { ticker: 'MSFT', weight: 0.6 },
    ]);
  });

  it('市值不可用时按股数降级计算权重', () => {
    const positions = buildAttributionPositions(summary([
      { ticker: 'aapl', shares: 1, market_value: 0, cost_basis: 0 },
      { ticker: 'msft', shares: 3, market_value: 0, cost_basis: 0 },
    ]));

    expect(positions).toEqual([
      { ticker: 'AAPL', weight: 0.25 },
      { ticker: 'MSFT', weight: 0.75 },
    ]);
  });
});
