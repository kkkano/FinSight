/**
 * SentimentStatsBar - Three sentiment cards with progress bars.
 *
 * Counts news items by simple keyword matching and renders
 * Positive / Neutral / Negative percentages.
 */
import { useMemo } from 'react';

import type { NewsItem } from '../../../../types/dashboard.ts';
import { DashboardSourceBadge } from '../../DashboardSourceBadge';
import { computeSentimentStats, currentNewsSamples } from '../../../../utils/news';

interface SentimentStatsBarProps {
  news: NewsItem[];
}

export function SentimentStatsBar({ news }: SentimentStatsBarProps) {
  const samples = useMemo(() => currentNewsSamples(news), [news]);
  const stats = useMemo(() => computeSentimentStats(samples), [samples]);

  const cards: { label: string; value: number; color: string; barColor: string }[] = [
    { label: '积极', value: stats.positive, color: 'text-fin-success', barColor: 'bg-fin-success' },
    { label: '中性', value: stats.neutral, color: 'text-fin-muted', barColor: 'bg-fin-muted' },
    { label: '消极', value: stats.negative, color: 'text-fin-danger', barColor: 'bg-fin-danger' },
  ];

  return (
    <div className="grid grid-cols-3 gap-3">
      {cards.map((card) => (
        <div
          key={card.label}
          className="bg-fin-card border border-fin-border rounded-lg p-3"
        >
          <div className="flex items-baseline justify-between mb-2">
            <span className="text-xs text-fin-muted">{card.label}</span>
            <div className="flex items-center gap-2">
              <span className={`text-sm font-semibold ${card.color}`}>
                {samples.length === 0 ? '--' : `${card.value}%`}
              </span>
              <DashboardSourceBadge metaKey="news_market" fallbackSource="hybrid_news" />
            </div>
          </div>
          <div className="h-1.5 bg-fin-border rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-500 ${card.barColor}`}
              style={{ width: `${card.value}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

export default SentimentStatsBar;
