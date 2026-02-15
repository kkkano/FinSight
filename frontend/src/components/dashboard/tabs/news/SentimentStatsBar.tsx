/**
 * SentimentStatsBar - Three sentiment cards with progress bars.
 *
 * Counts news items by simple keyword matching and renders
 * Positive / Neutral / Negative percentages.
 */
import { useMemo } from 'react';

import type { NewsItem } from '../../../../types/dashboard.ts';

// --- keyword lists for naive sentiment classification ---
const POSITIVE_KEYWORDS = [
  'surge', 'jump', 'rise', 'gain', 'bull', 'rally', 'upgrade', 'beat',
  'profit', 'growth', 'record', 'high', 'strong', 'positive', 'optimis',
  'outperform', 'buy', 'upside',
];

const NEGATIVE_KEYWORDS = [
  'drop', 'fall', 'decline', 'loss', 'bear', 'crash', 'downgrade', 'miss',
  'debt', 'risk', 'weak', 'negative', 'pessimis', 'sell', 'cut', 'low',
  'slump', 'warning', 'fear',
];

function classifyItem(item: NewsItem): 'positive' | 'negative' | 'neutral' {
  const text = `${item.title ?? ''} ${item.summary ?? ''}`.toLowerCase();
  const posHits = POSITIVE_KEYWORDS.filter((kw) => text.includes(kw)).length;
  const negHits = NEGATIVE_KEYWORDS.filter((kw) => text.includes(kw)).length;
  if (posHits > negHits) return 'positive';
  if (negHits > posHits) return 'negative';
  return 'neutral';
}

interface SentimentStatsBarProps {
  news: NewsItem[];
}

export function SentimentStatsBar({ news }: SentimentStatsBarProps) {
  const stats = useMemo(() => {
    const total = news.length;
    if (total === 0) return { positive: 0, neutral: 0, negative: 0 };
    let pos = 0;
    let neg = 0;
    for (const item of news) {
      const cls = classifyItem(item);
      if (cls === 'positive') pos += 1;
      else if (cls === 'negative') neg += 1;
    }
    const neu = total - pos - neg;
    return {
      positive: Math.round((pos / total) * 100),
      neutral: Math.round((neu / total) * 100),
      negative: Math.round((neg / total) * 100),
    };
  }, [news]);

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
            <span className={`text-sm font-semibold ${card.color}`}>
              {news.length === 0 ? '--' : `${card.value}%`}
            </span>
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
