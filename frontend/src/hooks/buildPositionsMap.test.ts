import { describe, expect, it } from 'vitest';

import { buildPositionsMap } from './usePortfolioSummary';
import type { PortfolioSummaryResponse, PortfolioSummaryPosition } from '../api/client';

function makePosition(overrides: Partial<PortfolioSummaryPosition>): PortfolioSummaryPosition {
  return {
    ticker: 'AAPL',
    shares: 10,
    market_value: 2000,
    cost_basis: 1500,
    ...overrides,
  };
}

function makeSummary(positions: PortfolioSummaryPosition[]): PortfolioSummaryResponse {
  return {
    success: true,
    session_id: 's-1',
    positions,
    count: positions.length,
    total_value: 0,
    total_cost: 0,
    total_pnl: 0,
  };
}

describe('buildPositionsMap', () => {
  it('builds a {ticker: shares} map from normal data', () => {
    const data = makeSummary([
      makePosition({ ticker: 'AAPL', shares: 10 }),
      makePosition({ ticker: 'TSLA', shares: 5 }),
    ]);
    expect(buildPositionsMap(data)).toEqual({ AAPL: 10, TSLA: 5 });
  });

  it('returns empty object for null data', () => {
    expect(buildPositionsMap(null)).toEqual({});
  });

  it('returns empty object for an empty positions array', () => {
    expect(buildPositionsMap(makeSummary([]))).toEqual({});
  });

  it('uppercases tickers and filters out non-positive / blank entries', () => {
    const data = makeSummary([
      makePosition({ ticker: 'aapl', shares: 3 }),
      makePosition({ ticker: 'TSLA', shares: 0 }),
      makePosition({ ticker: '  ', shares: 7 }),
      makePosition({ ticker: 'NVDA', shares: -2 }),
    ]);
    expect(buildPositionsMap(data)).toEqual({ AAPL: 3 });
  });

  it('tolerates a missing positions field', () => {
    // @ts-expect-error 故意构造异常 payload
    expect(buildPositionsMap({ success: true })).toEqual({});
  });
});
