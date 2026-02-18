/**
 * NewsCard — Rich news card with tags, impact badges, and action buttons.
 *
 * Features:
 * - Topic tags (computed client-side via computeNewsTags)
 * - Impact level badge (high/medium/low)
 * - Source reliability indicator
 * - "问这条" (Ask about) + "分析影响" (Analyze impact) action buttons
 * - Selection checkbox for MiniChat context
 * - Relative time display
 */
import { ExternalLink, Loader2, MessageCircleQuestion, Sparkles } from 'lucide-react';

import type { NewsItem, SelectionItem } from '../../../../types/dashboard';
import { generateNewsId } from '../../../../utils/hash';
import { computeNewsTags, deriveImpactLevel, formatNewsTime } from '../../../../utils/news';

interface NewsCardProps {
  news: NewsItem;
  ticker?: string;
  isSelected?: boolean;
  onToggleSelect?: (selection: SelectionItem) => void;
  onAskAbout?: (selection: SelectionItem) => void;
  onAnalyze?: (title: string) => void;
  isAnalyzing?: boolean;
}

// Impact level badge styles
const IMPACT_STYLES: Record<string, string> = {
  high: 'bg-red-500/15 text-red-500 dark:text-red-400',
  medium: 'bg-amber-500/15 text-amber-500 dark:text-amber-400',
  low: 'bg-gray-500/10 text-gray-400',
};

const IMPACT_LABELS: Record<string, string> = {
  high: '高影响',
  medium: '中影响',
  low: '低影响',
};

// Source reliability tier
function getReliabilityTier(score: number): { label: string; className: string } {
  if (score >= 0.9) return { label: '权威', className: 'text-fin-success' };
  if (score >= 0.75) return { label: '可靠', className: 'text-fin-warning' };
  return { label: '', className: 'text-fin-muted' };
}

// Tag colors by category
const TAG_COLORS: Record<string, string> = {
  '财报': 'bg-blue-500/12 text-blue-600 dark:text-blue-400',
  '科技': 'bg-purple-500/12 text-purple-600 dark:text-purple-400',
  'AI': 'bg-violet-500/12 text-violet-600 dark:text-violet-400',
  '半导体': 'bg-indigo-500/12 text-indigo-600 dark:text-indigo-400',
  '宏观': 'bg-orange-500/12 text-orange-600 dark:text-orange-400',
  '金融': 'bg-amber-500/12 text-amber-600 dark:text-amber-400',
  '并购': 'bg-cyan-500/12 text-cyan-600 dark:text-cyan-400',
  '监管': 'bg-rose-500/12 text-rose-600 dark:text-rose-400',
  '地缘': 'bg-red-500/12 text-red-600 dark:text-red-400',
  '军事': 'bg-red-500/12 text-red-600 dark:text-red-400',
  '能源': 'bg-lime-500/12 text-lime-600 dark:text-lime-400',
  '汽车': 'bg-sky-500/12 text-sky-600 dark:text-sky-400',
  '消费': 'bg-pink-500/12 text-pink-600 dark:text-pink-400',
  '医药': 'bg-teal-500/12 text-teal-600 dark:text-teal-400',
  '地产': 'bg-stone-500/12 text-stone-600 dark:text-stone-400',
  '加密': 'bg-yellow-500/12 text-yellow-600 dark:text-yellow-400',
  '中国': 'bg-red-500/12 text-red-600 dark:text-red-400',
  '美国': 'bg-blue-500/12 text-blue-600 dark:text-blue-400',
};

const DEFAULT_TAG_COLOR = 'bg-fin-border/30 text-fin-muted';

export function NewsCard({
  news,
  isSelected = false,
  onToggleSelect,
  onAskAbout,
  onAnalyze,
  isAnalyzing = false,
}: NewsCardProps) {
  const newsId = generateNewsId(news.title, news.source, news.ts);
  const tags = computeNewsTags(news);
  const impactLevel = deriveImpactLevel(news);
  const reliability = news.source_reliability ?? 0;
  const reliabilityTier = getReliabilityTier(reliability);

  const selection: SelectionItem = {
    type: 'news',
    id: newsId,
    title: news.title,
    url: news.url,
    source: news.source,
    ts: news.ts,
    snippet: (news.summary || news.title || '').slice(0, 100),
  };

  const handleCardClick = () => {
    if (news.url && news.url !== '#') {
      window.open(news.url, '_blank', 'noopener,noreferrer');
    }
  };

  return (
    <div
      data-testid={`news-card-${newsId}`}
      onClick={handleCardClick}
      className={`group p-3 rounded-lg border transition-all hover:shadow-sm ${
        isSelected
          ? 'border-fin-primary bg-fin-primary/5'
          : 'border-fin-border/50 hover:border-fin-border hover:bg-fin-hover/40'
      } ${news.url && news.url !== '#' ? 'cursor-pointer' : ''}`}
    >
      {/* Row 1: Tags + Source */}
      <div className="flex items-center justify-between gap-2 mb-1.5">
        <div className="flex items-center gap-1 flex-wrap min-w-0">
          {/* Topic tags */}
          {tags.map((tag) => (
            <span
              key={tag}
              className={`inline-flex px-1.5 py-0.5 rounded text-2xs font-medium ${
                TAG_COLORS[tag] ?? DEFAULT_TAG_COLOR
              }`}
            >
              {tag}
            </span>
          ))}
          {/* Impact badge */}
          <span className={`inline-flex px-1.5 py-0.5 rounded text-2xs font-medium ${IMPACT_STYLES[impactLevel]}`}>
            {IMPACT_LABELS[impactLevel]}
          </span>
        </div>

        {/* Source + reliability */}
        {news.source && (
          <span className={`shrink-0 text-2xs font-medium ${reliabilityTier.className}`}>
            {news.source}
            {reliabilityTier.label && (
              <span className="ml-1 opacity-60">({reliabilityTier.label})</span>
            )}
          </span>
        )}
      </div>

      {/* Row 2: Checkbox + Title */}
      <div className="flex items-start gap-2">
        {onToggleSelect && (
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onToggleSelect(selection); }}
            data-testid={`news-select-${newsId}`}
            title={isSelected ? '取消选择' : '选择'}
            aria-pressed={isSelected}
            aria-label={isSelected ? `取消选择 ${news.title}` : `选择 ${news.title}`}
            className={`mt-0.5 h-4 w-4 rounded border flex items-center justify-center shrink-0 transition-colors ${
              isSelected
                ? 'bg-fin-primary border-fin-primary'
                : 'border-fin-border bg-transparent hover:border-fin-primary'
            }`}
          >
            {isSelected ? <span className="text-white text-2xs leading-none">✓</span> : null}
          </button>
        )}

        <div className="flex-1 min-w-0">
          <h4 className="text-sm font-medium text-fin-text line-clamp-2 group-hover:text-fin-primary transition-colors">
            {news.title}
          </h4>

          {news.summary && (
            <p className="text-xs text-fin-muted mt-1 line-clamp-2">{news.summary}</p>
          )}
        </div>
      </div>

      {/* Row 3: Meta + Actions */}
      <div className="flex items-center justify-between mt-2">
        <div className="flex items-center gap-2 text-2xs text-fin-muted">
          <span>{formatNewsTime(news.ts)}</span>
          {typeof news.ranking_score === 'number' && (
            <>
              <span>·</span>
              <span className="text-fin-primary">评分 {news.ranking_score.toFixed(2)}</span>
            </>
          )}
          {typeof news.asset_relevance === 'number' && news.asset_relevance > 0 && (
            <>
              <span>·</span>
              <span className="text-fin-warning">相关 {(news.asset_relevance * 100).toFixed(0)}%</span>
            </>
          )}
        </div>

        <div className="flex items-center gap-0.5">
          {/* Analyze impact */}
          {onAnalyze && (
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); onAnalyze(news.title); }}
              disabled={isAnalyzing}
              title="分析影响"
              aria-label={`分析 ${news.title} 的市场影响`}
              className={`p-1.5 rounded-lg transition-all ${
                isAnalyzing
                  ? 'text-fin-muted opacity-50 cursor-not-allowed'
                  : 'text-fin-muted opacity-0 group-hover:opacity-100 hover:bg-amber-500/10 hover:text-amber-400'
              }`}
            >
              {isAnalyzing ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
            </button>
          )}

          {/* Ask about */}
          {onAskAbout && (
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); onAskAbout(selection); }}
              data-testid={`news-ask-${newsId}`}
              title="问这条"
              aria-label={`询问关于 ${news.title}`}
              className={`p-1.5 rounded-lg transition-all ${
                isSelected
                  ? 'bg-fin-primary text-white'
                  : 'text-fin-muted opacity-0 group-hover:opacity-100 hover:bg-fin-primary/10 hover:text-fin-primary'
              }`}
            >
              <MessageCircleQuestion size={13} />
            </button>
          )}

          {/* External link */}
          {news.url && news.url !== '#' && (
            <ExternalLink
              size={13}
              className="text-fin-muted opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
            />
          )}
        </div>
      </div>
    </div>
  );
}

export default NewsCard;
