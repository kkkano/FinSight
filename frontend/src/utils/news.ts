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

export function newsPublishedAt(item: NewsItem): string {
  return item.event_quality ? item.event_quality.published_at || '' : item.ts || '';
}

export function newsIdentity(item: NewsItem): string {
  const published = newsPublishedAt(item);
  if (item.event_quality?.event_id) return `${item.event_quality.event_id}:${published.slice(0, 10)}`;
  return JSON.stringify([item.url || item.title, published, item.url ? '' : item.source || '']);
}

export function deduplicateNews(items: NewsItem[]): NewsItem[] {
  const seen = new Set<string>();
  const result: NewsItem[] = [];
  const ordered = [...items].sort((a, b) => Number(isCurrentNewsSample(b)) - Number(isCurrentNewsSample(a)));
  for (const item of ordered) {
    const keys = [newsIdentity(item)];
    if (item.url) keys.push(JSON.stringify(['article', item.url, newsPublishedAt(item)]));
    if (keys.some((key) => seen.has(key))) continue;
    keys.forEach((key) => seen.add(key));
    result.push(item);
  }
  return result;
}

export function isCurrentNewsSample(item: NewsItem, now = Date.now()): boolean {
  const quality = item.event_quality;
  if (!quality || quality.usable_as_catalyst !== true || quality.freshness !== 'fresh'
    || quality.content_kind !== 'report' || !['headline', 'market'].includes(quality.subject_match || '')
    || !['primary', 'established_media'].includes(quality.source_tier || '')) return false;
  const published = Date.parse(quality.published_at || '');
  const maxHours = Math.min(quality.max_age_hours ?? 168, 168);
  return Number.isFinite(published) && maxHours > 0 && now - published <= maxHours * 3600000
    && published <= now + 300000;
}

export function currentNewsSamples(items: NewsItem[], now = Date.now()): NewsItem[] {
  return deduplicateNews(items.filter((item) => isCurrentNewsSample(item, now)));
}

export function newsQualityLabels(item: NewsItem): string[] {
  const quality = item.event_quality;
  if (!quality) return Number.isFinite(Date.parse(item.ts))
    ? ['出处与时效待核实'] : ['出处与时效待核实', '发布时间未知'];
  const labels: string[] = [];
  if (quality.freshness === 'stale' || (quality.freshness === 'fresh'
    && Number.isFinite(Date.parse(quality.published_at || ''))
    && Date.now() - Date.parse(quality.published_at!) > Math.min(quality.max_age_hours ?? 168, 168) * 3600000)) labels.push('旧闻背景');
  if (quality.freshness === 'unknown' || !Number.isFinite(Date.parse(quality.published_at || ''))) labels.push('发布时间未知');
  if (quality.freshness === 'future') labels.push('发布时间异常');
  if (quality.content_kind === 'opinion') labels.push('观点');
  if (quality.content_kind === 'rumor') labels.push('传闻待核实');
  if (quality.content_kind === 'discovery') labels.push('检索线索');
  if (['none', 'summary_only'].includes(quality.subject_match || '')) labels.push('主体关联待确认');
  if (quality.source_tier === 'unknown') labels.push('来源待核实');
  if (quality.content_kind === 'report') labels.push('报道待核原文');
  return labels.length ? labels : ['出处与时效待核实'];
}

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
  if (!ts) return '发布时间未知';
  try {
    const date = new Date(ts);
    if (!Number.isFinite(date.getTime())) return '发布时间未知';
    if (/^\d{4}-\d{2}-\d{2}$/.test(ts)) return ts;
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    if (diffMs < -300000) return '发布时间异常';
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
    const timestamp = Date.parse(newsPublishedAt(item));
    return !Number.isFinite(timestamp) || timestamp >= cutoff.getTime();
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
  return currentNewsSamples(items).filter((item) =>
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
  news = currentNewsSamples(news);
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
