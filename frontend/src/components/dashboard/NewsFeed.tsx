import { useMemo, useState } from 'react';
import { ExternalLink, MessageCircleQuestion, Newspaper, TrendingUp } from 'lucide-react';

import { useDashboardStore } from '../../store/dashboardStore';
import type { NewsItem, NewsModeType, SelectionItem } from '../../types/dashboard';
import { generateNewsId } from '../../utils/hash';

interface NewsFeedProps {
  marketNews: NewsItem[];
  impactNews: NewsItem[];
  marketRawNews?: NewsItem[];
  impactRawNews?: NewsItem[];
  rankingFormula?: string;
  rankingVersion?: string;
  rankingNotes?: string[];
  loading?: boolean;
}

export function NewsFeed({
  marketNews,
  impactNews,
  marketRawNews = [],
  impactRawNews = [],
  rankingFormula,
  rankingVersion,
  rankingNotes = [],
  loading,
}: NewsFeedProps) {
  const { activeAsset, newsMode, setNewsMode } = useDashboardStore();
  const [localMode, setLocalMode] = useState<NewsModeType>(newsMode);
  const [displayMode, setDisplayMode] = useState<'ranked' | 'raw'>('ranked');

  const handleModeChange = (mode: NewsModeType) => {
    setLocalMode(mode);
    setNewsMode(mode);
  };

  const currentNews = useMemo(() => {
    if (localMode === 'market') {
      return displayMode === 'raw' ? (marketRawNews.length > 0 ? marketRawNews : marketNews) : marketNews;
    }
    return displayMode === 'raw' ? (impactRawNews.length > 0 ? impactRawNews : impactNews) : impactNews;
  }, [displayMode, impactNews, impactRawNews, localMode, marketNews, marketRawNews]);

  const formatTime = (ts: string) => {
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
      return ts.split('T')[0] || ts;
    } catch {
      return ts;
    }
  };

  if (loading) {
    return (
      <div className="bg-fin-card border border-fin-border rounded-xl p-4">
        <div className="h-4 bg-fin-border rounded w-24 mb-4" />
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="animate-pulse">
              <div className="h-4 bg-fin-border rounded w-3/4 mb-2" />
              <div className="h-3 bg-fin-border rounded w-1/4" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="bg-fin-card border border-fin-border rounded-xl p-4">
      <div className="flex items-center justify-between mb-3 pb-3 border-b border-fin-border/60">
        <h3 className="text-sm font-semibold text-fin-text">新闻动态</h3>
        <div className="flex bg-fin-bg-secondary rounded-lg p-0.5">
          <button
            type="button"
            onClick={() => handleModeChange('market')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors transition-transform active:scale-95 ${
              localMode === 'market'
                ? 'bg-fin-card text-fin-primary shadow-sm'
                : 'text-fin-muted hover:text-fin-text'
            }`}
          >
            <Newspaper size={12} />
            Market 7x24
          </button>
          <button
            type="button"
            onClick={() => handleModeChange('impact')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors transition-transform active:scale-95 ${
              localMode === 'impact'
                ? 'bg-fin-card text-fin-primary shadow-sm'
                : 'text-fin-muted hover:text-fin-text'
            }`}
          >
            <TrendingUp size={12} />
            Impact
            {activeAsset ? <span className="text-fin-muted">({activeAsset.symbol})</span> : null}
          </button>
        </div>
      </div>

      <div className="flex items-center justify-between mb-3">
        <div className="text-[11px] text-fin-muted">
          {displayMode === 'ranked' ? '按策略排序' : '原始新闻流'}
        </div>
        <div className="flex items-center gap-1 bg-fin-bg-secondary rounded-lg p-0.5">
          <button
            type="button"
            onClick={() => setDisplayMode('ranked')}
            className={`px-2 py-1 text-[11px] rounded ${
              displayMode === 'ranked' ? 'bg-fin-card text-fin-primary' : 'text-fin-muted hover:text-fin-text'
            }`}
          >
            排序
          </button>
          <button
            type="button"
            onClick={() => setDisplayMode('raw')}
            className={`px-2 py-1 text-[11px] rounded ${
              displayMode === 'raw' ? 'bg-fin-card text-fin-primary' : 'text-fin-muted hover:text-fin-text'
            }`}
          >
            原始
          </button>
        </div>
      </div>

      {displayMode === 'ranked' && rankingFormula ? (
        <div className="mb-3 rounded border border-fin-border/60 bg-fin-bg-secondary/40 px-2.5 py-1.5 text-2xs text-fin-muted">
          <div>排序依据：{rankingFormula}</div>
          {rankingVersion ? <div>版本：{rankingVersion}</div> : null}
          {rankingNotes.length > 0 ? <div>说明：{rankingNotes.join('；')}</div> : null}
        </div>
      ) : null}

      {currentNews.length === 0 ? (
        <div className="flex items-center justify-center h-32 text-fin-muted text-sm">
          {localMode === 'market' ? '暂无市场新闻' : '暂无相关新闻'}
        </div>
      ) : (
        <div className="space-y-3 max-h-64 overflow-y-auto pr-1">
          {currentNews.map((news, index) => (
            <NewsItemCard
              key={`${news.title}-${index}`}
              news={news}
              formatTime={formatTime}
              showRanking={displayMode === 'ranked'}
            />
          ))}
        </div>
      )}
    </div>
  );
}

interface NewsItemCardProps {
  news: NewsItem;
  formatTime: (ts: string) => string;
  showRanking?: boolean;
}

function NewsItemCard({ news, formatTime, showRanking = false }: NewsItemCardProps) {
  const { activeSelections, setActiveSelection, toggleSelection } = useDashboardStore();

  const newsId = generateNewsId(news.title, news.source, news.ts);
  const isSelected = activeSelections.some((s) => s.id === newsId);

  const selection: SelectionItem = {
    type: 'news',
    id: newsId,
    title: news.title,
    url: news.url,
    source: news.source,
    ts: news.ts,
    snippet: (news.summary || news.title || '').slice(0, 100),
  };

  const handleClick = () => {
    if (news.url && news.url !== '#') {
      window.open(news.url, '_blank');
    }
  };

  const handleAskAbout = (event: React.MouseEvent) => {
    event.stopPropagation();
    setActiveSelection(selection);
  };

  const handleToggleSelect = (event: React.MouseEvent) => {
    event.stopPropagation();
    toggleSelection(selection);
  };

  return (
    <div
      onClick={handleClick}
      data-testid={`news-item-${newsId}`}
      className={`group p-3 rounded-lg border transition-colors transition-shadow hover:shadow-sm ${
        isSelected
          ? 'border-fin-primary bg-fin-primary/5'
          : 'border-transparent hover:border-fin-border hover:bg-fin-hover/40'
      } ${news.url && news.url !== '#' ? 'cursor-pointer' : ''}`}
    >
      <div className="flex items-start justify-between gap-2">
        <button
          type="button"
          onClick={handleToggleSelect}
          data-testid={`news-select-${newsId}`}
          title={isSelected ? '取消选择' : '选择'}
          className={`mt-0.5 h-4 w-4 rounded border flex items-center justify-center shrink-0 transition-colors ${
            isSelected
              ? 'bg-fin-primary border-fin-primary'
              : 'border-fin-border bg-transparent hover:border-fin-primary'
          }`}
          aria-pressed={isSelected}
          aria-label={isSelected ? `取消选择 ${news.title}` : `选择 ${news.title}`}
        >
          {isSelected ? <span className="text-white text-2xs leading-none">✓</span> : null}
        </button>

        <div className="flex-1 min-w-0">
          <h4 className="text-sm font-medium text-fin-text line-clamp-2 group-hover:text-fin-primary transition-colors">
            {news.title}
          </h4>

          {news.summary ? (
            <p className="text-xs text-fin-muted mt-1 line-clamp-2">
              {news.summary}
            </p>
          ) : null}

          <div className="flex items-center gap-2 mt-2 text-2xs text-fin-muted">
            {news.source ? (
              <>
                <span>{news.source}</span>
                <span>·</span>
              </>
            ) : null}
            <span>{formatTime(news.ts)}</span>
            {showRanking && typeof news.ranking_score === 'number' ? (
              <>
                <span>·</span>
                <span className="text-fin-primary">score {news.ranking_score.toFixed(2)}</span>
              </>
            ) : null}
          </div>

          {showRanking && news.ranking_reason ? (
            <div className="mt-1 text-2xs text-fin-muted">{news.ranking_reason}</div>
          ) : null}
        </div>

        <div className="flex items-center gap-1 shrink-0 mt-1">
          <button
            type="button"
            onClick={handleAskAbout}
            data-testid={`news-ask-${newsId}`}
            title="问这条"
            aria-label={`询问关于 ${news.title}`}
            className={`p-1.5 rounded-lg transition-all ${
              isSelected
                ? 'bg-fin-primary text-white'
                : 'text-fin-muted opacity-0 group-hover:opacity-100 hover:bg-fin-primary/10 hover:text-fin-primary'
            }`}
          >
            <MessageCircleQuestion size={14} />
          </button>

          {news.url && news.url !== '#' ? (
            <ExternalLink
              size={14}
              className="text-fin-muted opacity-0 group-hover:opacity-100 transition-opacity"
            />
          ) : null}
        </div>
      </div>
    </div>
  );
}

export default NewsFeed;

