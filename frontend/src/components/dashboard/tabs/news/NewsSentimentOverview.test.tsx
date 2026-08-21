import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import type { NewsItem, NewsSentimentSnapshot } from '../../../../types/dashboard';
import {
  hasUsablePriceTransmission,
  mapBackendCatalystEvents,
  NewsSentimentOverview,
  resolveBackendTrend,
} from './NewsSentimentOverview';

const news: NewsItem[] = [
  {
    title: 'AAPL shares surge on record profit',
    url: 'https://example.com/a',
    source: 'Reuters',
    ts: '2026-08-20T08:00:00Z',
    summary: 'strong growth',
  },
  {
    title: 'Routine platform update',
    url: 'https://example.com/b',
    source: 'CNBC',
    ts: '2026-08-20T09:00:00Z',
  },
];

const snapshot: NewsSentimentSnapshot = {
  ticker: 'AAPL',
  source: 'dashboard_light_snapshot',
  sentiment_bias: {
    label: 'bullish',
    positive_count: 2,
    negative_count: 0,
    neutral_count: 1,
    sample_size: 3,
    basis: 'keyword_estimation',
  },
  sentiment_trend: {
    direction: 'improving',
    delta: 0.5,
    recent_average: 0.8,
    previous_average: 0.3,
    sample_size: 3,
    basis: 'half_window_comparison',
  },
  heat: { level: 'active', news_count: 3, basis: 'news_volume' },
  catalyst_events: {
    count: 1,
    events: [
      {
        title: 'AAPL beats Q2 earnings',
        date: '2026-08-20T08:00:00Z',
        source: 'Reuters',
        impact_score: 0.9,
      },
    ],
  },
  price_transmission: {
    status: 'divergence',
    analysis: '舆情偏多但近期价格走弱。',
    source: 'backend',
    price_change_pct: -1.2,
  },
};

describe('resolveBackendTrend', () => {
  it('maps improving / deteriorating / unknown backend directions', () => {
    expect(resolveBackendTrend(snapshot)).toEqual({ direction: 'up', label: '转暖', delta: 0.5 });
    expect(
      resolveBackendTrend({
        ...snapshot,
        sentiment_trend: { ...snapshot.sentiment_trend, direction: 'deteriorating', delta: -0.4 },
      }),
    ).toEqual({ direction: 'down', label: '走弱', delta: -0.4 });
    expect(resolveBackendTrend({ ...snapshot, sentiment_trend: { ...snapshot.sentiment_trend, direction: 'unknown', delta: null } })).toBeNull();
  });
});

describe('mapBackendCatalystEvents', () => {
  it('maps backend catalyst events into the timeline contract', () => {
    const events = mapBackendCatalystEvents(snapshot.catalyst_events.events);
    expect(events).toHaveLength(1);
    expect(events[0].title).toBe('AAPL beats Q2 earnings');
    expect(events[0].sentiment).toBe('bullish');
  });
});

describe('hasUsablePriceTransmission', () => {
  it('treats todo / unknown as unavailable', () => {
    expect(hasUsablePriceTransmission('resonance')).toBe(true);
    expect(hasUsablePriceTransmission('divergence')).toBe(true);
    expect(hasUsablePriceTransmission('todo')).toBe(false);
    expect(hasUsablePriceTransmission('unknown')).toBe(false);
    expect(hasUsablePriceTransmission('')).toBe(false);
  });
});

describe('NewsSentimentOverview', () => {
  it('prefers backend snapshot for trend, catalysts and price transmission', () => {
    const html = renderToStaticMarkup(
      <NewsSentimentOverview news={news} timeRange="24h" snapshot={snapshot} />,
    );
    expect(html).toContain('后端舆情快照优先');
    expect(html).toContain('转暖');
    expect(html).toContain('后端半窗对比');
    expect(html).toContain('AAPL beats Q2 earnings');
    expect(html).toContain('背离');
    expect(html).toContain('舆情偏多但近期价格走弱。');
  });

  it('keeps client fallback when snapshot is absent', () => {
    const html = renderToStaticMarkup(
      <NewsSentimentOverview news={news} timeRange="24h" />,
    );
    expect(html).toContain('客户端时间线估算');
    expect(html).not.toContain('舆情偏多但近期价格走弱。');
    expect(html).toContain('待接入');
  });

  it('does not fabricate price transmission when backend status is todo', () => {
    const todoSnapshot: NewsSentimentSnapshot = {
      ...snapshot,
      price_transmission: { status: 'todo', reason: 'no evidence', source: null, price_change_pct: null },
    };
    const html = renderToStaticMarkup(
      <NewsSentimentOverview news={news} timeRange="24h" snapshot={todoSnapshot} />,
    );
    expect(html).toContain('不推断');
    expect(html).not.toContain('>背离<');
  });
});
