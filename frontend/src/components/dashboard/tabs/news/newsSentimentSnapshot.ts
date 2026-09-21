import type { NewsItem, NewsSentimentSnapshot } from '../../../../types/dashboard';
import { classifySentiment, type SentimentType } from '../../../../utils/news';

export type TrendDirection = 'up' | 'down' | 'flat' | 'insufficient';

export interface CatalystEvent {
  id: string;
  title: string;
  source: string;
  ts: string;
  sentiment: SentimentType;
  impactScore: number;
}

const TREND_DIRECTION_MAP: Record<string, TrendDirection> = {
  improving: 'up',
  deteriorating: 'down',
  stable: 'flat',
};

const TREND_LABEL_MAP: Record<string, string> = {
  improving: '转暖',
  deteriorating: '走弱',
  stable: '震荡',
};

export function resolveBackendTrend(
  snapshot?: NewsSentimentSnapshot,
): { direction: TrendDirection; label: string; delta: number } | null {
  const trend = snapshot?.sentiment_trend;
  if (!trend || trend.direction === 'unknown' || typeof trend.delta !== 'number') {
    return null;
  }
  return {
    direction: TREND_DIRECTION_MAP[trend.direction] ?? 'flat',
    label: TREND_LABEL_MAP[trend.direction] ?? '震荡',
    delta: trend.delta,
  };
}

export function mapBackendCatalystEvents(
  events: NewsSentimentSnapshot['catalyst_events']['events'],
): CatalystEvent[] {
  return events.slice(0, 5).map((event, index) => ({
    id: `backend-${event.title}-${event.date ?? ''}-${index}`,
    title: event.title ?? '',
    source: event.source ?? '',
    ts: event.date ?? '',
    sentiment: classifySentiment({ title: event.title ?? '', summary: '', url: '', ts: '' } as NewsItem),
    impactScore: typeof event.impact_score === 'number' ? event.impact_score : 0.5,
  }));
}

export function hasUsablePriceTransmission(status: string): boolean {
  return status !== '' && status !== 'todo' && status !== 'unknown';
}
