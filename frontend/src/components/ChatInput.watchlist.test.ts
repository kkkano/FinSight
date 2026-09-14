import { describe, expect, it } from 'vitest';

import { buildChatSuggestions } from './chatSuggestions';

describe('buildChatSuggestions', () => {
  it('uses the first four watchlist tickers', () => {
    const suggestions = buildChatSuggestions([
      { symbol: 'aapl' },
      { symbol: 'MSFT' },
      { symbol: 'NVDA' },
      { symbol: 'TSLA' },
      { symbol: 'GOOGL' },
    ]);

    expect(suggestions).toHaveLength(4);
    expect(suggestions.map((item) => item.label)).toEqual([
      '> AAPL 分析',
      '> MSFT 分析',
      '> NVDA 分析',
      '> TSLA 分析',
    ]);
    expect(suggestions[0].prompt).toContain('AAPL');
  });

  it('keeps the four built-in suggestions when watchlist is empty', () => {
    const suggestions = buildChatSuggestions([]);
    expect(suggestions).toHaveLength(4);
    expect(suggestions[3].report).toBe(true);
  });
});
