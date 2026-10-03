import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { NewsItem } from '../types/dashboard';
import { computeSentimentStats, currentNewsSamples, deduplicateNews, filterBreakingNews,
  filterByTimeRange, formatNewsTime, newsQualityLabels } from './news';

const NOW = '2026-10-03T12:00:00Z';
export const qualityNews = (overrides: Partial<NewsItem> = {}): NewsItem => ({
  title: 'INTC earnings beat expectations', url: 'https://www.reuters.com/intc-update',
  source: 'Reuters', ts: '2026-10-03T10:00:00Z', impact_score: 0.9, source_reliability: 0.9,
  event_quality: { version: 'news-event-v1', event_id: 'event:intc:2026-10-03',
    published_at: '2026-10-03T10:00:00Z', freshness: 'fresh', source_tier: 'established_media',
    subject_match: 'headline', content_kind: 'report', usable_as_catalyst: true,
    verification: 'headline_only', max_age_hours: 168 },
  ...overrides,
});

describe('news event consumption contract', () => {
  beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(NOW); });
  afterEach(() => vi.useRealTimers());

  it.each([
    { freshness: 'stale' }, { freshness: 'unknown' }, { freshness: 'future' },
    { subject_match: 'none' }, { subject_match: 'summary_only' },
    { content_kind: 'opinion' }, { content_kind: 'rumor' }, { content_kind: 'discovery' },
    { published_at: null }, { published_at: '2026-09-01T10:00:00Z' },
    { source_tier: 'unknown' }, { usable_as_catalyst: false },
  ] as const)('excludes unqualified headlines despite high scores: %j', (quality) => {
    const valid = qualityNews();
    const invalid = { ...qualityNews(), event_quality: { ...valid.event_quality, ...quality } };
    expect(currentNewsSamples([invalid])).toEqual([]);
    expect(filterBreakingNews([invalid])).toEqual([]);
    expect(computeSentimentStats([invalid])).toEqual({ positive: 0, neutral: 0, negative: 0 });
  });

  it('never treats unannotated cached headlines as verified current samples', () => {
    const legacy = qualityNews({ event_quality: undefined });
    expect(currentNewsSamples([legacy])).toEqual([]);
    expect(newsQualityLabels(legacy)).toContain('出处与时效待核实');
  });

  it('deduplicates a current event across syndication without counting sources as events', () => {
    const article = qualityNews();
    const duplicate = { ...article, source: 'Yahoo', url: 'https://finance.yahoo.com/news/intc' };
    expect(currentNewsSamples([article, duplicate])).toHaveLength(1);
    expect(computeSentimentStats([article, duplicate])).toEqual({ positive: 100, neutral: 0, negative: 0 });
  });

  it('keeps cross-day updates to the same URL and title, including legacy rows', () => {
    const current = qualityNews();
    const previous = { ...current, ts: '2026-10-02T10:00:00Z', event_quality: {
      ...current.event_quality, event_id: 'event:intc:2026-10-02', published_at: '2026-10-02T10:00:00Z',
    } };
    expect(deduplicateNews([current, previous])).toHaveLength(2);
    expect(deduplicateNews([{ ...current, event_quality: undefined }, { ...previous, event_quality: undefined }])).toHaveLength(2);
  });

  it('merges same-URL same-time title updates without swallowing a different publication time', () => {
    const current = qualityNews();
    const updated = { ...current, title: 'INTC earnings update', event_quality: { ...current.event_quality, event_id: 'event:updated' } };
    expect(deduplicateNews([current, updated])).toHaveLength(1);
  });

  it('keeps unknown-time original entries visible and labels them rather than inventing freshness', () => {
    const unknown = qualityNews({ ts: NOW, event_quality: { published_at: null, freshness: 'unknown', content_kind: 'discovery' } });
    expect(filterByTimeRange([unknown], '24h')).toEqual([unknown]);
    expect(newsQualityLabels(unknown)).toEqual(['发布时间未知', '检索线索']);
    expect(formatNewsTime('')).toBe('发布时间未知');
    expect(formatNewsTime('invalid')).toBe('发布时间未知');
    expect(formatNewsTime('2026-10-04T12:00:00Z')).toBe('发布时间异常');
    expect(formatNewsTime('2026-10-03')).toBe('2026-10-03');
  });

  it('labels qualified reports as unverified original reporting, never confirmed events', () => {
    expect(newsQualityLabels(qualityNews())).toEqual(['报道待核原文']);
    expect(newsQualityLabels(qualityNews({ event_quality: { freshness: 'stale', published_at: '2026-09-01', content_kind: 'opinion' } })))
      .toEqual(['旧闻背景', '观点']);
  });
});
