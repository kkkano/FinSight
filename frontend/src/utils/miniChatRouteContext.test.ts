import { describe, expect, it } from 'vitest';

import { getMiniChatRouteSymbol, routeSupportsMiniChat } from './miniChatRouteContext';

describe('mini chat route context', () => {
  it('uses the dashboard route symbol before stale store state', () => {
    expect(getMiniChatRouteSymbol('/dashboard/aapl', 'MSFT')).toBe('AAPL');
  });

  it('uses dashboard store state when the route has no symbol', () => {
    expect(getMiniChatRouteSymbol('/dashboard', 'nvda')).toBe('NVDA');
  });

  it('does not leak a stale ticker into workbench context', () => {
    expect(getMiniChatRouteSymbol('/workbench', 'TSLA')).toBeNull();
    expect(routeSupportsMiniChat('/workbench')).toBe(true);
    expect(routeSupportsMiniChat('/chat')).toBe(false);
  });
});
