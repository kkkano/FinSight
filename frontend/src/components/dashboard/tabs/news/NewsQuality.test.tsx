import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import type { NewsItem } from '../../../../types/dashboard';
import { NewsCard } from './NewsCard';
import { computeOverviewStats } from './NewsSentimentOverview';
import { SentimentStatsBar } from './SentimentStatsBar';

const render = (node: ReactNode) => renderToStaticMarkup(
  <QueryClientProvider client={new QueryClient()}>{node}</QueryClientProvider>,
);

const article: NewsItem = { title: 'INTC earnings beat', url: 'https://www.reuters.com/intc', source: 'Reuters',
  ts: '2026-10-03T10:00:00Z', impact_score: 0.9, source_reliability: 0.9,
  event_quality: { event_id: 'intc-2026-10-03', published_at: '2026-10-03T10:00:00Z', freshness: 'fresh',
    source_tier: 'established_media', subject_match: 'headline', content_kind: 'report', usable_as_catalyst: true,
    verification: 'headline_only', max_age_hours: 168 },
};

describe('news presentation quality', () => {
  beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime('2026-10-03T12:00:00Z'); });
  afterEach(() => vi.useRealTimers());

  it('shows a concise original-verification label on qualified reports', () => {
    const html = render(<NewsCard news={article} />);
    expect(html).toContain('报道待核原文');
    expect(html).toContain('高影响');
  });

  it('shows opinion and unknown publication labels without promoting impact or authority', () => {
    const html = render(<NewsCard news={{ ...article, event_quality: {
      freshness: 'unknown', published_at: null, content_kind: 'opinion', source_tier: 'opinion_or_community',
    } }} />);
    expect(html).toContain('观点');
    expect(html).toContain('发布时间未知');
    expect(html).not.toContain('高影响');
    expect(html).not.toContain('(权威)');
  });

  it('counts only distinct qualified events in catalysts, heat and sentiment', () => {
    const stale: NewsItem = { ...article, title: 'INTC slump', event_quality: {
      ...article.event_quality, event_id: 'stale', freshness: 'stale', published_at: '2026-08-01',
    } };
    const stats = computeOverviewStats([article, { ...article, source: 'Yahoo' }, stale,
      { ...article, event_quality: undefined }], '30d');
    expect(stats.total).toBe(1);
    expect(stats.bullish).toBe(1);
    expect(stats.bearish).toBe(0);
    expect(stats.highImpactCount).toBe(1);
    expect(stats.catalysts).toHaveLength(1);
    expect(stats.timeline).toHaveLength(1);
  });

  it('keeps empty or old-cache aggregates as insufficient rather than fabricated heat', () => {
    const stats = computeOverviewStats([{ ...article, event_quality: undefined }], '7d');
    expect(stats.total).toBe(0);
    expect(stats.heatScore).toBe(0);
    expect(stats.biasLabel).toBe('样本不足');
    expect(stats.catalysts).toEqual([]);
    const html = render(<SentimentStatsBar news={[{ ...article, event_quality: undefined }]} />);
    expect(html).toContain('--');
    expect(html).not.toContain('100%');
  });
});
