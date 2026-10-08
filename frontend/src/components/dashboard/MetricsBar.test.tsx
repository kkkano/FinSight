import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { MetricsBar } from './MetricsBar';
import { formatDividendYield } from '../../utils/format';
import { ValuationGrid } from './tabs/financial/ValuationGrid';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

describe('formatDividendYield', () => {
  it('formats the declared ratio without guessing its unit from magnitude', () => {
    expect(formatDividendYield(0.36)).toBe('36.00%');
    expect(formatDividendYield(0.86)).toBe('86.00%');
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
          dividend_yield: 0.0036,
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

  it('renders the same canonical dividend ratio in the strip and valuation grid', () => {
    const valuation = { dividend_yield: 1.08 / 341.005 };
    const html = renderToStaticMarkup(
      <QueryClientProvider client={new QueryClient()}>
        <MetricsBar valuation={valuation} />
        <ValuationGrid valuation={valuation} />
      </QueryClientProvider>,
    );
    expect(html.match(/0\.32%/g)).toHaveLength(2);
    expect(html).not.toContain('32.00%');
  });
});
