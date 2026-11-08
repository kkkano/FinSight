import { describe, expect, it } from 'vitest';
import { safeLoginDestination } from './authOptions';

describe('login destination', () => {
  it.each(['//outside.example', '/\\outside.example', 'https://outside.example', '/welcome?from=x', ''])('rejects non-local or recursive destination %s', (from) => {
    expect(safeLoginDestination(from)).toBe('/dashboard/AAPL');
  });
  it('keeps an application route and its encoded query', () => {
    expect(safeLoginDestination('/chat?q=NVDA')).toBe('/chat?q=NVDA');
  });
});

