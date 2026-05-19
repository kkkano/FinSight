import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { MetricsBar, formatDividendYield } from './MetricsBar';

describe('formatDividendYield', () => {
  it('keeps provider percent-point dividend yields from being multiplied again', () => {
    expect(formatDividendYield(0.36)).toBe('0.36%');
    expect(formatDividendYield(0.86)).toBe('0.86%');
  });

  it('still supports ratio-style dividend yields for small values', () => {
    expect(formatDividendYield(0.0036)).toBe('0.36%');
    expect(formatDividendYield(0.036)).toBe('3.60%');
  });
});

describe('MetricsBar', () => {
  it('renders corrected dividend yield values', () => {
    const html = renderToStaticMarkup(
      <MetricsBar
        valuation={{
          market_cap: 4_370_000_000_000,
          trailing_pe: 36.1,
          price_to_book: 41,
          dividend_yield: 0.36,
          week52_low: 193.46,
          week52_high: 303.2,
          beta: 1.1,
        }}
        snapshot={{ eps: 8.25 }}
      />,
    );

    expect(html).toContain('0.36%');
    expect(html).not.toContain('36.00%');
  });
});
