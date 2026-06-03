import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { PriceDriftBannerView } from './PriceDriftBanner';
import type { PriceDriftResult } from './PriceDriftBanner';

const renderText = (node: React.ReactElement) =>
  renderToStaticMarkup(node).replace(/\s+/g, ' ');

const baseResult = (overrides: Partial<PriceDriftResult> = {}): PriceDriftResult => ({
  ticker: 'AAPL',
  report_price: 100,
  current_price: 105,
  drift_pct: 5,
  report_age_hours: 3,
  threshold_pct: 2,
  significant: true,
  ...overrides,
});

describe('PriceDriftBannerView', () => {
  it('renders nothing when result is null', () => {
    expect(renderToStaticMarkup(<PriceDriftBannerView result={null} />)).toBe('');
  });

  it('renders nothing when result is not significant', () => {
    const result = baseResult({ significant: false });
    expect(renderToStaticMarkup(<PriceDriftBannerView result={result} />)).toBe('');
  });

  it('renders amber banner with full price comparison when significant', () => {
    const text = renderText(<PriceDriftBannerView result={baseResult()} />);
    expect(text).toContain('本报告生成于');
    expect(text).toContain('100.00');
    expect(text).toContain('105.00');
    expect(text).toContain('+5.0%');
    expect(text).toContain('结论可能需要重新评估');
    // 琥珀色样式
    expect(text).toContain('amber');
  });

  it('formats negative drift with sign', () => {
    const result = baseResult({ current_price: 95, drift_pct: -5 });
    const text = renderText(<PriceDriftBannerView result={result} />);
    expect(text).toContain('-5.0%');
  });

  it('falls back to age-only message when price comparison is unavailable', () => {
    // 实时价拿不到（current_price=null）→ 仅时效提示，不编造价差
    const result = baseResult({
      current_price: null,
      drift_pct: null,
      report_age_hours: 30,
      significant: true,
    });
    const text = renderText(<PriceDriftBannerView result={result} />);
    expect(text).toContain('市场行情可能已发生变化');
    expect(text).not.toContain('变动');
  });

  it('formats age in days when over 48 hours', () => {
    const result = baseResult({
      current_price: null,
      drift_pct: null,
      report_age_hours: 72,
    });
    const text = renderText(<PriceDriftBannerView result={result} />);
    expect(text).toContain('3 天前');
  });
});
