import { type ReactNode, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowRight, Inbox, MessageCircleQuestion, Newspaper } from 'lucide-react';

import { Badge } from '../ui/Badge';
import { Card } from '../ui/Card';
import type { NewsItem, SelectionItem, WatchItem } from '../../types/dashboard';
import { useDashboardStore } from '../../store/dashboardStore';
import { useStore } from '../../store/useStore';
import { generateNewsId } from '../../utils/hash';

type NewsViewMode = 'ranked' | 'raw';
type SentimentLabel = 'positive' | 'negative' | 'neutral';

interface NewsSectionProps {
  symbol: string;
  newsItems: NewsItem[];
  rawNewsItems: NewsItem[];
  rankingMeta?: {
    version?: string;
    formula?: string;
    notes?: string[];
  };
  watchlist?: WatchItem[];
}

const MAX_VISIBLE = 12;

const POSITIVE_KEYWORDS = ['surge', 'jump', 'beat', 'strong', 'rally', 'gain', 'soar', 'boom'];
const NEGATIVE_KEYWORDS = ['drop', 'fall', 'miss', 'weak', 'risk', 'crash', 'plunge', 'slump', 'decline'];

function classifySentiment(title: string): SentimentLabel {
  const lower = title.toLowerCase();
  for (const keyword of POSITIVE_KEYWORDS) {
    if (lower.includes(keyword)) return 'positive';
  }
  for (const keyword of NEGATIVE_KEYWORDS) {
    if (lower.includes(keyword)) return 'negative';
  }
  return 'neutral';
}

function SentimentBadge({ sentiment }: { sentiment: SentimentLabel }) {
  if (sentiment === 'positive') {
    return <Badge variant="success">利好</Badge>;
  }
  if (sentiment === 'negative') {
    return <Badge variant="danger">利空</Badge>;
  }
  return <Badge variant="default">中性</Badge>;
}

/**
 * Highlight ticker keywords found in the title by wrapping them with <mark>.
 * We build a single regex from all watchlist symbols for efficiency.
 */
function highlightTickers(title: string, tickers: string[]): ReactNode {
  if (tickers.length === 0) return title;

  // Escape regex special chars and join with |
  const escaped = tickers.map((t) =>
    t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'),
  );
  const pattern = new RegExp(`\\b(${escaped.join('|')})\\b`, 'gi');
  const parts = title.split(pattern);

  if (parts.length <= 1) return title;

  return (
    <>
      {parts.map((part, idx) => {
        const isMatch = tickers.some(
          (t) => t.toLowerCase() === part.toLowerCase(),
        );
        return isMatch ? (
          <mark
            key={`${part}-${String(idx)}`}
            className="bg-fin-primary/20 text-fin-primary rounded-sm px-0.5"
          >
            {part}
          </mark>
        ) : (
          <span key={`${part}-${String(idx)}`}>{part}</span>
        );
      })}
    </>
  );
}

function NewsSkeleton() {
  return (
    <div className="space-y-2">
      {Array.from({ length: 3 }).map((_, i) => (
        <div
          key={`news-skeleton-${String(i)}`}
          className="p-2 rounded-lg border border-fin-border animate-pulse"
        >
          <div className="h-3.5 bg-fin-bg-secondary rounded w-full" />
          <div className="h-3.5 bg-fin-bg-secondary rounded w-2/3 mt-1" />
          <div className="h-2.5 bg-fin-bg-secondary rounded w-1/3 mt-2" />
        </div>
      ))}
    </div>
  );
}

function NewsEmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-6 text-fin-muted gap-2">
      <Inbox size={28} strokeWidth={1.5} />
      <span className="text-xs">暂无快讯</span>
    </div>
  );
}

function NewsSection({
  symbol,
  newsItems,
  rawNewsItems,
  rankingMeta,
  watchlist = [],
}: NewsSectionProps) {
  const navigate = useNavigate();
  const { setActiveSelection } = useDashboardStore();
  const { setDraft } = useStore();

  const [newsViewMode, setNewsViewMode] = useState<NewsViewMode>('ranked');

  const watchlistTickers = useMemo(
    () => watchlist.map((w) => w.symbol),
    [watchlist],
  );

  const rankedNewsItems = useMemo(
    () =>
      [...newsItems].sort((a, b) => {
        const scoreDelta =
          Number(b.ranking_score ?? -1) - Number(a.ranking_score ?? -1);
        if (scoreDelta !== 0) return scoreDelta;

        const bTs = Date.parse(String(b.ts || ''));
        const aTs = Date.parse(String(a.ts || ''));
        if (!Number.isNaN(bTs) && !Number.isNaN(aTs) && bTs !== aTs) {
          return bTs - aTs;
        }

        return String(a.title || '').localeCompare(String(b.title || ''));
      }),
    [newsItems],
  );

  const workbenchNews =
    newsViewMode === 'raw'
      ? rawNewsItems.length > 0
        ? rawNewsItems
        : newsItems
      : rankedNewsItems;

  const isLoading = newsItems.length === 0 && rawNewsItems.length === 0;

  const askAboutNews = (news: NewsItem) => {
    const selection: SelectionItem = {
      type: 'news',
      id: generateNewsId(news.title, news.source, news.ts),
      title: news.title,
      url: news.url,
      source: news.source,
      ts: news.ts,
      snippet: (news.summary || news.title || '').slice(0, 160),
    };
    setActiveSelection(selection);
    setDraft(`基于这条快讯继续分析：${news.title}`);
    navigate('/chat');
  };

  return (
    <Card className="p-4 md:col-span-2">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2 text-fin-text font-semibold text-sm">
          <Newspaper size={16} className="text-fin-primary" />
          市场快讯
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1 bg-fin-bg-secondary rounded-md p-0.5">
            <button
              type="button"
              onClick={() => setNewsViewMode('ranked')}
              className={`px-2 py-1 text-[11px] rounded ${newsViewMode === 'ranked' ? 'bg-fin-card text-fin-primary' : 'text-fin-muted hover:text-fin-text'}`}
            >
              排序
            </button>
            <button
              type="button"
              onClick={() => setNewsViewMode('raw')}
              className={`px-2 py-1 text-[11px] rounded ${newsViewMode === 'raw' ? 'bg-fin-card text-fin-primary' : 'text-fin-muted hover:text-fin-text'}`}
            >
              原始
            </button>
          </div>
          <button
            type="button"
            onClick={() =>
              navigate(`/dashboard/${encodeURIComponent(symbol)}`)
            }
            className="text-xs text-fin-primary hover:underline inline-flex items-center gap-1"
          >
            去仪表盘
            <ArrowRight size={12} />
          </button>
        </div>
      </div>

      <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
        {/* Ranking meta info */}
        {newsViewMode === 'ranked' && rankingMeta?.formula ? (
          <div className="rounded-lg border border-fin-border/60 bg-fin-bg-secondary/40 px-2.5 py-1.5 text-2xs text-fin-muted">
            <div>排序依据：{rankingMeta.formula}</div>
            {rankingMeta.version ? (
              <div>版本：{rankingMeta.version}</div>
            ) : null}
            {Array.isArray(rankingMeta.notes) && rankingMeta.notes.length > 0 ? (
              <div>说明：{rankingMeta.notes.join('；')}</div>
            ) : null}
          </div>
        ) : null}

        {/* Loading skeleton */}
        {isLoading ? <NewsSkeleton /> : null}

        {/* Empty state */}
        {!isLoading && workbenchNews.length === 0 ? <NewsEmptyState /> : null}

        {/* News items */}
        {workbenchNews.slice(0, MAX_VISIBLE).map((news, idx) => {
          const sentiment = classifySentiment(news.title);
          return (
            <div
              key={`${news.title}-${String(idx)}`}
              className="p-2 rounded-lg border border-fin-border transition-colors transition-shadow hover:bg-fin-hover/40 hover:shadow-sm"
            >
              <div className="flex items-start gap-2">
                <div className="flex-1 min-w-0">
                  <div className="text-xs text-fin-text font-medium line-clamp-2">
                    {highlightTickers(news.title, watchlistTickers)}
                  </div>
                </div>
                <SentimentBadge sentiment={sentiment} />
              </div>
              <div className="text-2xs text-fin-muted mt-1">
                {news.source || 'unknown'} &middot; {news.ts || 'unknown'}
                {typeof news.ranking_score === 'number' &&
                newsViewMode === 'ranked'
                  ? ` \u00B7 score ${news.ranking_score.toFixed(2)}`
                  : ''}
              </div>
              {newsViewMode === 'ranked' && news.ranking_reason ? (
                <div className="text-2xs text-fin-muted mt-1">
                  {news.ranking_reason}
                </div>
              ) : null}
              <div className="mt-2 flex items-center gap-2">
                <button
                  type="button"
                  data-testid={`workbench-ask-news-${String(idx)}`}
                  onClick={() => askAboutNews(news)}
                  className="text-[11px] px-2 py-1 rounded-lg border border-fin-primary/40 text-fin-primary hover:bg-fin-primary/10 inline-flex items-center gap-1"
                >
                  <MessageCircleQuestion size={12} />
                  问这条
                </button>
                {news.url ? (
                  <a
                    href={news.url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-[11px] text-fin-muted hover:text-fin-primary"
                  >
                    原文
                  </a>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

export { NewsSection };
export type { NewsSectionProps };
