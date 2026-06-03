import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { CNMarketNotice } from './CNMarketNotice';

describe('CNMarketNotice', () => {
  it('renders the T+1 / limit notice for A-share tickers', () => {
    const html = renderToStaticMarkup(<CNMarketNotice ticker="600519.SS" />);
    expect(html).toContain('A股交易制度');
    expect(html).toContain('T+1');
    expect(html).toContain('±10%');
  });

  it('renders nothing for HK tickers', () => {
    expect(renderToStaticMarkup(<CNMarketNotice ticker="0700.HK" />)).toBe('');
  });

  it('renders nothing for US tickers', () => {
    expect(renderToStaticMarkup(<CNMarketNotice ticker="AAPL" />)).toBe('');
  });

  it('renders nothing for empty ticker', () => {
    expect(renderToStaticMarkup(<CNMarketNotice ticker="" />)).toBe('');
  });
});
