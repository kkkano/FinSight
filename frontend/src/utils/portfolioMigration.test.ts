import { describe, expect, it } from 'vitest';

import {
  parseLegacyPositions,
  shouldMigrate,
  type LegacyPosition,
} from './portfolioMigration';
import type { PortfolioSummaryPosition } from '../api/client';

function makeBackendPosition(ticker: string, shares: number): PortfolioSummaryPosition {
  return {
    ticker,
    shares,
    market_value: 0,
    cost_basis: 0,
  };
}

describe('parseLegacyPositions', () => {
  it('parses a valid {ticker: shares} dictionary', () => {
    const raw = JSON.stringify({ AAPL: 10, TSLA: 5 });
    expect(parseLegacyPositions(raw)).toEqual([
      { ticker: 'AAPL', shares: 10 },
      { ticker: 'TSLA', shares: 5 },
    ]);
  });

  it('uppercases tickers and drops invalid entries', () => {
    const raw = JSON.stringify({ aapl: 3, tsla: 0, '  ': 7, nvda: -2, msft: 'x' });
    expect(parseLegacyPositions(raw)).toEqual([{ ticker: 'AAPL', shares: 3 }]);
  });

  it('returns [] for null / empty / malformed JSON', () => {
    expect(parseLegacyPositions(null)).toEqual([]);
    expect(parseLegacyPositions('')).toEqual([]);
    expect(parseLegacyPositions('not-json')).toEqual([]);
    expect(parseLegacyPositions('[]')).toEqual([]);
    expect(parseLegacyPositions('"str"')).toEqual([]);
  });
});

describe('shouldMigrate', () => {
  const local: LegacyPosition[] = [{ ticker: 'AAPL', shares: 10 }];

  it('migrates when local has data and backend is empty', () => {
    expect(shouldMigrate(local, [])).toBe(true);
    expect(shouldMigrate(local, null)).toBe(true);
    expect(shouldMigrate(local, undefined)).toBe(true);
  });

  it('does NOT migrate when backend already has positions (never overwrite)', () => {
    expect(shouldMigrate(local, [makeBackendPosition('TSLA', 5)])).toBe(false);
  });

  it('does NOT migrate when local is empty', () => {
    expect(shouldMigrate([], [])).toBe(false);
    expect(shouldMigrate([], [makeBackendPosition('TSLA', 5)])).toBe(false);
  });
});
