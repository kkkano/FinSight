/**
 * NewsTab - Container component for the News tab panel.
 *
 * Combines SentimentStatsBar, NewsFilterPills, AiNewsSummaryCard,
 * and a filtered news list using data from dashboardStore and useLatestReport.
 */
import { useMemo, useState } from 'react';
import { ExternalLink } from 'lucide-react';

import { useDashboardStore } from '../../../store/dashboardStore.ts';
import { useLatestReport } from '../../../hooks/useLatestReport.ts';
import type { NewsItem } from '../../../types/dashboard.ts';
import { SentimentStatsBar } from './news/SentimentStatsBar.tsx';
import { NewsFilterPills } from './news/NewsFilterPills.tsx';
import type { NewsFilterType } from './news/NewsFilterPills.tsx';
import { AiNewsSummaryCard } from './news/AiNewsSummaryCard.tsx';

// --- Keyword sets matching the sentiment classification in SentimentStatsBar ---

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
  const posHits = POSITIVE_KEYWORDS.filter((kw) => text.includes(kw)).length;
  const negHits = NEGATIVE_KEYWORDS.filter((kw) => text.includes(kw)).length;
  if (posHits > negHits) return 'bullish';
  if (negHits > posHits) return 'bearish';
  return 'neutral';
}

function formatNewsTime(ts: string): string {
  if (!ts) return '';
  try {
    const date = new Date(ts);
    const now = new Date();
    const diff = now.getTime() - date.getTime();
    const hours = Math.floor(diff / (1000 * 60 * 60));
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
  const [activeFilter, setActiveFilter] = useState<NewsFilterType>('all');

  const ticker = activeAsset?.symbol ?? null;
  const { data: reportData, loading: reportLoading } = useLatestReport(ticker);

  // Combine market + impact news
  const allNews = useMemo<NewsItem[]>(() => {
    if (!dashboardData?.news) return [];
    const market = dashboardData.news.market ?? [];
    const impact = dashboardData.news.impact ?? [];
    // Deduplicate by title
    const seen = new Set<string>();
    const combined: NewsItem[] = [];
    for (const item of [...market, ...impact]) {
      if (!seen.has(item.title)) {
        seen.add(item.title);
        combined.push(item);
      }
    }
    return combined;
  }, [dashboardData?.news]);

  // Apply filter
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
      {/* AI Summary */}
      <AiNewsSummaryCard reportData={reportData} loading={reportLoading} />

      {/* Sentiment statistics */}
      <SentimentStatsBar news={allNews} />

      {/* Filter pills */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-fin-text">
          新闻列表
          <span className="ml-2 text-xs text-fin-muted font-normal">
            ({filteredNews.length})
          </span>
        </h3>
        <NewsFilterPills activeFilter={activeFilter} onFilterChange={setActiveFilter} />
      </div>

      {/* News list */}
      {filteredNews.length === 0 ? (
        <div className="flex items-center justify-center h-32 text-fin-muted text-sm">
          暂无匹配的新闻
        </div>
      ) : (
        <div className="space-y-2 max-h-[500px] overflow-y-auto pr-1">
          {filteredNews.map((news, idx) => (
            <a
              key={`${news.title}-${idx}`}
              href={news.url && news.url !== '#' ? news.url : undefined}
              target="_blank"
              rel="noopener noreferrer"
              className="group block p-3 rounded-lg border border-transparent hover:border-fin-border hover:bg-fin-hover/40 transition-colors"
            >
              <div className="flex items-start justify-between gap-2">
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
          ))}
        </div>
      )}
    </div>
  );
}

export default NewsTab;
