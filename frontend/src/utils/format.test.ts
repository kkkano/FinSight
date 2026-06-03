import { describe, expect, it } from 'vitest';

import {
  currencySymbolForTicker,
  formatMarketCapForMarket,
  formatPriceForMarket,
  isAShareTicker,
} from './format';

describe('currencySymbolForTicker', () => {
  it('maps A-share suffixes to ¥', () => {
    expect(currencySymbolForTicker('600519.SS')).toBe('¥');
    expect(currencySymbolForTicker('300750.SZ')).toBe('¥');
    expect(currencySymbolForTicker('430047.BJ')).toBe('¥');
  });

  it('maps HK suffix to HK$', () => {
    expect(currencySymbolForTicker('0700.HK')).toBe('HK$');
  });

  it('defaults to $ for US and unknown', () => {
    expect(currencySymbolForTicker('AAPL')).toBe('$');
    expect(currencySymbolForTicker('')).toBe('$');
    expect(currencySymbolForTicker(null)).toBe('$');
  });
});

describe('isAShareTicker', () => {
  it('detects A-share tickers only', () => {
    expect(isAShareTicker('600519.SS')).toBe(true);
    expect(isAShareTicker('300750.SZ')).toBe(true);
    expect(isAShareTicker('0700.HK')).toBe(false);
    expect(isAShareTicker('AAPL')).toBe(false);
  });
});

describe('formatPriceForMarket', () => {
  it('prefixes A-share prices with ¥', () => {
    expect(formatPriceForMarket(1688, '600519.SS')).toBe('¥1,688.00');
  });

  it('prefixes HK prices with HK$', () => {
    expect(formatPriceForMarket(320.5, '0700.HK')).toBe('HK$320.50');
  });

  it('prefixes US prices with $', () => {
    expect(formatPriceForMarket(150.25, 'AAPL')).toBe('$150.25');
  });

  it('returns -- for nullish/NaN', () => {
    expect(formatPriceForMarket(null, '600519.SS')).toBe('--');
    expect(formatPriceForMarket(NaN, 'AAPL')).toBe('--');
  });
});

describe('formatMarketCapForMarket', () => {
  it('uses 万亿/亿 units for A-shares', () => {
    expect(formatMarketCapForMarket(2.1e12, '600519.SS')).toBe('¥2.10万亿');
    expect(formatMarketCapForMarket(4.5e11, '600519.SS')).toBe('¥4500.0亿');
  });

  it('uses 亿 with HK$ prefix for HK stocks', () => {
    expect(formatMarketCapForMarket(3.4e12, '0700.HK')).toBe('HK$3.40万亿');
  });

  it('uses T/B/M units for US stocks', () => {
    expect(formatMarketCapForMarket(3.4e12, 'AAPL')).toBe('$3.40T');
    expect(formatMarketCapForMarket(4.37e11, 'AAPL')).toBe('$437.00B');
  });

  it('returns -- for nullish', () => {
    expect(formatMarketCapForMarket(null, 'AAPL')).toBe('--');
  });
});
