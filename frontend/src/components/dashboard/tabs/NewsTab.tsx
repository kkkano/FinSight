import { useMemo, useState } from 'react';
import { ExternalLink } from 'lucide-react';

import { useDashboardStore } from '../../../store/dashboardStore';
import { useLatestReport } from '../../../hooks/useLatestReport';
import type { NewsItem, SelectionItem } from '../../../types/dashboard';
import { generateNewsId } from '../../../utils/hash';
import { SentimentStatsBar } from './news/SentimentStatsBar';
import { NewsFilterPills } from './news/NewsFilterPills';
import type { NewsFilterType } from './news/NewsFilterPills';
import { AiNewsSummaryCard } from './news/AiNewsSummaryCard';
import { AiInsightCard } from './shared/AiInsightCard';

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

function classifySentiment(item: NewsItem): 'bullish' | 'bearish' | 'neutral' {
  const text = `${item.title ?? ''} ${item.summary ?? ''}`.toLowerCase();
  const positiveHits = POSITIVE_KEYWORDS.filter((keyword) => text.includes(keyword)).length;
  const negativeHits = NEGATIVE_KEYWORDS.filter((keyword) => text.includes(keyword)).length;

  if (positiveHits > negativeHits) return 'bullish';
  if (negativeHits > positiveHits) return 'bearish';
  return 'neutral';
}

function formatNewsTime(ts: string): string {
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

export function NewsTab() {
  const activeAsset = useDashboardStore((s) => s.activeAsset);
  const dashboardData = useDashboardStore((s) => s.dashboardData);
  const activeSelections = useDashboardStore((s) => s.activeSelections);
  const toggleSelection = useDashboardStore((s) => s.toggleSelection);
  const insightsData = useDashboardStore((s) => s.insightsData);
  const insightsLoading = useDashboardStore((s) => s.insightsLoading);
  const insightsError = useDashboardStore((s) => s.insightsError);
  const insightsStale = useDashboardStore((s) => s.insightsStale);

  const [activeFilter, setActiveFilter] = useState<NewsFilterType>('all');

  const ticker = activeAsset?.symbol ?? null;
  const { data: reportData, loading: reportLoading } = useLatestReport(ticker, {
    sourceType: 'dashboard',
    fallbackToAnySource: false,
  });

  const newsMarket = dashboardData?.news?.market;
  const newsImpact = dashboardData?.news?.impact;
  const newsInsight = insightsData?.news ?? null;

  const allNews = useMemo<NewsItem[]>(() => {
    if (!newsMarket && !newsImpact) return [];
    const market = newsMarket ?? [];
    const impact = newsImpact ?? [];

    const seen = new Set<string>();
    const merged: NewsItem[] = [];

    for (const item of [...market, ...impact]) {
      const dedupeKey = `${item.title || ''}::${item.source || ''}`;
      if (seen.has(dedupeKey)) continue;
      seen.add(dedupeKey);
      merged.push(item);
    }

    return merged;
  }, [newsMarket, newsImpact]);

  const filteredNews = useMemo(() => {
    if (activeFilter === 'all') return allNews;
    return allNews.filter((item) => classifySentiment(item) === activeFilter);
  }, [allNews, activeFilter]);

  if (!dashboardData) {
    return (
      <div className="flex items-center justify-center h-64 text-fin-muted text-sm">
        暂无数据，请先选择资产
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* AI News Insight Card — replaces AiNewsSummaryCard when insights available */}
      <AiInsightCard
        tab="news"
        insight={newsInsight}
        loading={insightsLoading}
        error={insightsError}
        stale={insightsStale}
      />
      {/* Fallback: report-based news summary (hidden when insight is present) */}
      {!newsInsight && !insightsLoading && (
        <AiNewsSummaryCard reportData={reportData} loading={reportLoading} />
      )}
      <SentimentStatsBar news={allNews} />

      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-fin-text">
          新闻列表
          <span className="ml-2 text-xs text-fin-muted font-normal">({filteredNews.length})</span>
        </h3>
        <NewsFilterPills activeFilter={activeFilter} onFilterChange={setActiveFilter} />
      </div>

      {filteredNews.length === 0 ? (
        <div className="flex items-center justify-center h-32 text-fin-muted text-sm">
          暂无匹配的新闻
        </div>
      ) : (
        <div className="space-y-2 max-h-[500px] overflow-y-auto pr-1">
          {filteredNews.map((news, idx) => {
            const newsId = generateNewsId(news.title, news.source, news.ts);
            const isSelected = activeSelections.some((item) => item.id === newsId);
            const selection: SelectionItem = {
              type: 'news',
              id: newsId,
              title: news.title,
              url: news.url,
              source: news.source,
              ts: news.ts,
              snippet: (news.summary || news.title || '').slice(0, 100),
            };

            return (
              <a
                key={`${news.title}-${idx}`}
                href={news.url && news.url !== '#' ? news.url : undefined}
                target="_blank"
                rel="noopener noreferrer"
                className={`group block p-3 rounded-lg border transition-colors ${
                  isSelected
                    ? 'border-fin-primary bg-fin-primary/5'
                    : 'border-transparent hover:border-fin-border hover:bg-fin-hover/40'
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <button
                    type="button"
                    data-testid={`news-select-${newsId}`}
                    title={isSelected ? '取消选择' : '选择'}
                    aria-label={isSelected ? `取消选择 ${news.title}` : `选择 ${news.title}`}
                    aria-pressed={isSelected}
                    onClick={(event) => {
                      event.preventDefault();
                      event.stopPropagation();
                      toggleSelection(selection);
                    }}
                    className={`mt-0.5 h-4 w-4 rounded border flex items-center justify-center shrink-0 transition-colors ${
                      isSelected
                        ? 'bg-fin-primary border-fin-primary'
                        : 'border-fin-border bg-transparent hover:border-fin-primary'
                    }`}
                  >
                    {isSelected ? <span className="text-white text-2xs leading-none">✓</span> : null}
                  </button>

                  <div className="flex-1 min-w-0">
                    <h4 className="text-sm font-medium text-fin-text line-clamp-2 group-hover:text-fin-primary transition-colors">
                      {news.title}
                    </h4>

                    {news.summary ? (
                      <p className="text-xs text-fin-muted mt-1 line-clamp-2">{news.summary}</p>
                    ) : null}

                    <div className="flex items-center gap-2 mt-1.5 text-2xs text-fin-muted">
                      {news.source ? <span>{news.source}</span> : null}
                      {news.source ? <span>·</span> : null}
                      <span>{formatNewsTime(news.ts)}</span>
                      {typeof news.ranking_score === 'number' ? (
                        <>
                          <span>·</span>
                          <span className="text-fin-primary">score {news.ranking_score.toFixed(2)}</span>
                        </>
                      ) : null}
                      {typeof news.asset_relevance === 'number' ? (
                        <>
                          <span>·</span>
                          <span className="text-fin-warning">
                            relevance {(news.asset_relevance * 100).toFixed(0)}%
                          </span>
                        </>
                      ) : null}
                    </div>
                  </div>

                  {news.url && news.url !== '#' ? (
                    <ExternalLink
                      size={14}
                      className="text-fin-muted opacity-0 group-hover:opacity-100 transition-opacity shrink-0 mt-1"
                    />
                  ) : null}
                </div>
              </a>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default NewsTab;
