/**
 * news.ts — Shared news utility functions.
 *
 * Provides sentiment classification, tag computation, time filtering,
 * and impact level derivation for the news system.
 * Eliminates code duplication between NewsTab, SentimentStatsBar, etc.
 */
import type { NewsItem, NewsTagGroup, NewsTimeRange } from '../types/dashboard';
import { NEWS_TAG_GROUP_MAP } from '../types/dashboard';

// ---------------------------------------------------------------------------
// Sentiment classification (keyword-based, unified across all components)
// ---------------------------------------------------------------------------

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

export type SentimentType = 'bullish' | 'neutral' | 'bearish';

export function classifySentiment(item: NewsItem): SentimentType {
  const text = `${item.title ?? ''} ${item.summary ?? ''}`.toLowerCase();
  const positiveHits = POSITIVE_KEYWORDS.filter((kw) => text.includes(kw)).length;
  const negativeHits = NEGATIVE_KEYWORDS.filter((kw) => text.includes(kw)).length;

  if (positiveHits > negativeHits) return 'bullish';
  if (negativeHits > positiveHits) return 'bearish';
  return 'neutral';
}

// ---------------------------------------------------------------------------
// Client-side tag computation (mirrors backend NEWS_TAG_RULES)
// Phase H1: runs on frontend; Phase H2 replaces with server-side tags
// ---------------------------------------------------------------------------

const TAG_RULES: [string, string[]][] = [
  ['科技', ['tech', 'technology', 'software', 'cloud', 'saas', 'platform']],
  ['AI', ['ai', 'artificial intelligence', 'genai', 'llm', 'machine learning', 'gpt', '大模型']],
  ['半导体', ['semiconductor', 'chip', 'nvidia', 'tsmc', 'asml', 'amd', 'intel']],
  ['宏观', ['cpi', 'gdp', 'fomc', 'inflation', 'fed', 'interest rate', 'pce', 'nonfarm']],
  ['金融', ['bank', 'bond', 'yield', 'treasury', 'credit']],
  ['财报', ['earnings', 'guidance', 'revenue', 'quarterly', 'q1', 'q2', 'q3', 'q4', 'eps']],
  ['并购', ['merger', 'acquisition', 'buyout', 'takeover', 'deal']],
  ['监管', ['regulator', 'antitrust', 'sec', 'doj', 'compliance', 'fine']],
  ['能源', ['oil', 'crude', 'gas', 'opec', 'energy', 'solar', 'wind']],
  ['汽车', ['ev', 'electric vehicle', 'auto', 'tesla', 'byd']],
  ['消费', ['consumer', 'retail', 'e-commerce', 'amazon']],
  ['医药', ['pharma', 'biotech', 'drug', 'fda', 'clinical']],
  ['地产', ['real estate', 'property', 'housing', 'mortgage']],
  ['加密', ['crypto', 'bitcoin', 'blockchain', 'btc', 'eth']],
  ['地缘', ['geopolitical', 'war', 'conflict', 'sanction', 'diplomacy']],
  ['军事', ['military', 'defense', 'missile', 'drone', 'nato']],
  ['中国', ['china', 'chinese', 'beijing', '中国']],
  ['美国', ['united states', 'u.s.', 'washington', '美国', 'white house']],
];

const MAX_TAGS = 3;

export function computeNewsTags(item: NewsItem): string[] {
  // If server already provided tags, use them
  if (item.tags && item.tags.length > 0) return item.tags;

  const text = `${item.title ?? ''} ${item.summary ?? ''}`.toLowerCase();
  const matched: string[] = [];

  for (const [tag, keywords] of TAG_RULES) {
    if (matched.length >= MAX_TAGS) break;
    if (keywords.some((kw) => text.includes(kw))) {
      matched.push(tag);
    }
  }

  return matched;
}

// ---------------------------------------------------------------------------
// Impact level derivation (from existing ranking scores)
// ---------------------------------------------------------------------------

export type ImpactLevel = 'high' | 'medium' | 'low';

export function deriveImpactLevel(item: NewsItem): ImpactLevel {
  if (item.impact_level) return item.impact_level;
  const score = item.impact_score ?? 0;
  if (score >= 0.6) return 'high';
  if (score >= 0.3) return 'medium';
  return 'low';
}

// ---------------------------------------------------------------------------
// Time formatting
// ---------------------------------------------------------------------------

export function formatNewsTime(ts: string): string {
  if (!ts) return '';
  try {
    const date = new Date(ts);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const hours = Math.floor(diffMs / (1000 * 60 * 60));
    const days = Math.floor(hours / 24);

    if (hours < 1) return '刚刚';
    if (hours < 24) return `${hours}小时前`;
    if (days < 7) return `${days}天前`;
    return ts.split('T')[0] ?? ts;
  } catch {
    return ts;
  }
}

// ---------------------------------------------------------------------------
// Time range filtering
// ---------------------------------------------------------------------------

export function getTimeCutoff(range: NewsTimeRange): Date {
  const now = new Date();
  switch (range) {
    case '24h': return new Date(now.getTime() - 24 * 60 * 60 * 1000);
    case '7d':  return new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
    case '30d': return new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
  }
}

export function filterByTimeRange(items: NewsItem[], range: NewsTimeRange): NewsItem[] {
  const cutoff = getTimeCutoff(range);
  return items.filter((item) => {
    try { return new Date(item.ts) >= cutoff; }
    catch { return true; }  // keep items with unparseable timestamps
  });
}

// ---------------------------------------------------------------------------
// Tag group filtering
// ---------------------------------------------------------------------------

export function filterByTagGroup(items: NewsItem[], group: NewsTagGroup): NewsItem[] {
  if (group === '全部') return items;
  const allowedTags = NEWS_TAG_GROUP_MAP[group];
  return items.filter((item) => {
    const tags = computeNewsTags(item);
    return tags.some((t) => allowedTags.includes(t));
  });
}

// ---------------------------------------------------------------------------
// Breaking news filter (high impact + high reliability)
// ---------------------------------------------------------------------------

const BREAKING_IMPACT_THRESHOLD = 0.6;
const BREAKING_RELIABILITY_THRESHOLD = 0.7;

export function filterBreakingNews(items: NewsItem[]): NewsItem[] {
  return items.filter((item) =>
    (item.impact_score ?? 0) >= BREAKING_IMPACT_THRESHOLD &&
    (item.source_reliability ?? 0) >= BREAKING_RELIABILITY_THRESHOLD,
  );
}

// ---------------------------------------------------------------------------
// Sentiment statistics (for SentimentStatsBar)
// ---------------------------------------------------------------------------

export interface SentimentStats {
  positive: number;
  neutral: number;
  negative: number;
}

export function computeSentimentStats(news: NewsItem[]): SentimentStats {
  const total = news.length;
  if (total === 0) return { positive: 0, neutral: 0, negative: 0 };

  let pos = 0;
  let neg = 0;
  for (const item of news) {
    const cls = classifySentiment(item);
    if (cls === 'bullish') pos += 1;
    else if (cls === 'bearish') neg += 1;
  }
  const neu = total - pos - neg;

  return {
    positive: Math.round((pos / total) * 100),
    neutral: Math.round((neu / total) * 100),
    negative: Math.round((neg / total) * 100),
  };
}
