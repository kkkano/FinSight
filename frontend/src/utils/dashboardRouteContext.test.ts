import { describe, expect, it } from 'vitest';

import { getDashboardRouteSymbol } from './dashboardRouteContext';

describe('dashboard route context', () => {
  it('uses the dashboard route symbol before stale store state', () => {
    expect(getDashboardRouteSymbol('/dashboard/aapl', 'MSFT')).toBe('AAPL');
  });

  it('uses dashboard store state when the route has no symbol', () => {
    expect(getDashboardRouteSymbol('/dashboard', 'nvda')).toBe('NVDA');
  });

  it('does not leak a stale ticker outside dashboard routes', () => {
    expect(getDashboardRouteSymbol('/history', 'TSLA')).toBeNull();
    expect(getDashboardRouteSymbol('/chat', 'TSLA')).toBeNull();
  });
});
