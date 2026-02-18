/**
 * NewsTab — Main news tab with three sub-views.
 *
 * Phase H redesign:
 * - Three sub-tabs: stock-specific / market 7x24 / breaking events
 * - Secondary topic filter chips (7 groups from 18 backend tags)
 * - Time range selector (24h / 7d / 30d)
 * - Rich NewsCard with tags, impact badges, and action buttons
 */
import { useMemo } from 'react';

import { useDashboardStore } from '../../../store/dashboardStore';
import { useLatestReport } from '../../../hooks/useLatestReport';
import { useExecuteAgent } from '../../../hooks/useExecuteAgent';
import type { NewsItem, SelectionItem, NewsTagGroup } from '../../../types/dashboard';
import { NEWS_TAG_GROUP_MAP } from '../../../types/dashboard';
import {
  computeNewsTags,
  filterByTimeRange,
  filterBreakingNews,
} from '../../../utils/news';
import { generateNewsId } from '../../../utils/hash';
import { SentimentStatsBar } from './news/SentimentStatsBar';
import { AiNewsSummaryCard } from './news/AiNewsSummaryCard';
import { AiInsightCard } from './shared/AiInsightCard';
import { NewsSubTabs } from './news/NewsSubTabs';
import { NewsTagChips } from './news/NewsTagChips';
import { NewsTimeRange } from './news/NewsTimeRange';
import { NewsCard } from './news/NewsCard';

// ---------------------------------------------------------------------------
// Deduplicate news items by title+source key
// ---------------------------------------------------------------------------
function deduplicateNews(items: NewsItem[]): NewsItem[] {
  const seen = new Set<string>();
  const result: NewsItem[] = [];
  for (const item of items) {
    const key = `${item.title || ''}::${item.source || ''}`;
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(item);
  }
  return result;
}

// ---------------------------------------------------------------------------
// Detect which tag groups have matching items
// ---------------------------------------------------------------------------
function detectAvailableGroups(items: NewsItem[]): NewsTagGroup[] {
  const groups: NewsTagGroup[] = [];
  const groupKeys = Object.keys(NEWS_TAG_GROUP_MAP) as NewsTagGroup[];

  for (const group of groupKeys) {
    if (group === '全部') continue;
    const allowed = NEWS_TAG_GROUP_MAP[group];
    const hasMatch = items.some((item) => {
      const tags = computeNewsTags(item);
      return tags.some((t) => allowed.includes(t));
    });
    if (hasMatch) groups.push(group);
  }

  return groups;
}

// ---------------------------------------------------------------------------
// Filter by tag group
// ---------------------------------------------------------------------------
function filterByTagGroup(items: NewsItem[], group: NewsTagGroup): NewsItem[] {
  if (group === '全部') return items;
  const allowed = NEWS_TAG_GROUP_MAP[group];
  return items.filter((item) => {
    const tags = computeNewsTags(item);
    return tags.some((t) => allowed.includes(t));
  });
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export function NewsTab() {
  // --- Store ---
  const activeAsset = useDashboardStore((s) => s.activeAsset);
  const dashboardData = useDashboardStore((s) => s.dashboardData);
  const newsSubTab = useDashboardStore((s) => s.newsSubTab);
  const newsTagFilter = useDashboardStore((s) => s.newsTagFilter);
  const newsTimeRange = useDashboardStore((s) => s.newsTimeRange);
  const setNewsSubTab = useDashboardStore((s) => s.setNewsSubTab);
  const setNewsTagFilter = useDashboardStore((s) => s.setNewsTagFilter);
  const setNewsTimeRange = useDashboardStore((s) => s.setNewsTimeRange);
  const activeSelections = useDashboardStore((s) => s.activeSelections);
  const toggleSelection = useDashboardStore((s) => s.toggleSelection);
  const setActiveSelection = useDashboardStore((s) => s.setActiveSelection);
  const insightsData = useDashboardStore((s) => s.insightsData);
  const insightsLoading = useDashboardStore((s) => s.insightsLoading);
  const insightsError = useDashboardStore((s) => s.insightsError);
  const insightsStale = useDashboardStore((s) => s.insightsStale);

  // --- Report fallback ---
  const ticker = activeAsset?.symbol ?? null;
  const { data: reportData, loading: reportLoading } = useLatestReport(ticker, {
    sourceType: 'dashboard',
    fallbackToAnySource: false,
  });
  const newsInsight = insightsData?.news ?? null;

  // --- Agent execution for "分析影响" ---
  const { execute: executeAnalysis, isRunning: isAnalyzing } = useExecuteAgent();

  // --- Raw data arrays ---
  const marketNews = useMemo(() => dashboardData?.news?.market ?? [], [dashboardData]);
  const impactNews = useMemo(() => dashboardData?.news?.impact ?? [], [dashboardData]);

  // --- Sub-tab counts (before time/tag filtering) ---
  const allCombined = useMemo(
    () => deduplicateNews([...marketNews, ...impactNews]),
    [marketNews, impactNews],
  );
  const breakingAll = useMemo(() => filterBreakingNews(allCombined), [allCombined]);
  const counts = useMemo(() => ({
    stock: impactNews.length,
    market: marketNews.length,
    breaking: breakingAll.length,
  }), [impactNews, marketNews, breakingAll]);

  // --- Step 1: Select data source by sub-tab ---
  const sourceNews = useMemo<NewsItem[]>(() => {
    switch (newsSubTab) {
      case 'stock':    return impactNews;
      case 'market':   return marketNews;
      case 'breaking': return breakingAll;
    }
  }, [newsSubTab, impactNews, marketNews, breakingAll]);

  // --- Step 2: Filter by tag group ---
  const tagFiltered = useMemo(
    () => filterByTagGroup(sourceNews, newsTagFilter),
    [sourceNews, newsTagFilter],
  );

  // --- Step 3: Filter by time range ---
  const timeFiltered = useMemo(
    () => filterByTimeRange(tagFiltered, newsTimeRange),
    [tagFiltered, newsTimeRange],
  );

  // --- Available tag groups (for dynamic chip rendering) ---
  const availableGroups = useMemo(
    () => detectAvailableGroups(sourceNews),
    [sourceNews],
  );

  // --- Handlers ---
  const handleAskAbout = (selection: SelectionItem) => {
    setActiveSelection(selection);
  };

  const handleAnalyze = (title: string) => {
    if (isAnalyzing || !ticker) return;
    executeAnalysis({
      query: `分析这条新闻的市场影响: ${title}`,
      tickers: [ticker],
      agents: ['news_agent'],
      source: 'dashboard_news',
    });
  };

  const handleToggleSelect = (selection: SelectionItem) => {
    toggleSelection(selection);
  };

  // --- Empty state ---
  if (!dashboardData) {
    return (
      <div className="flex items-center justify-center h-64 text-fin-muted text-sm">
        暂无数据，请先选择资产
      </div>
    );
  }

  // --- Render ---
  return (
    <div className="space-y-4">
      {/* AI News Insight Card (Phase F) */}
      <AiInsightCard
        tab="news"
        insight={newsInsight}
        loading={insightsLoading}
        error={insightsError}
        stale={insightsStale}
      />
      {/* Fallback: report-based summary */}
      {!newsInsight && !insightsLoading && (
        <AiNewsSummaryCard reportData={reportData} loading={reportLoading} />
      )}

      {/* Sub-tabs: stock / market / breaking */}
      <NewsSubTabs
        activeTab={newsSubTab}
        onTabChange={setNewsSubTab}
        ticker={ticker ?? undefined}
        counts={counts}
      />

      {/* Filters: tag chips + time range (same row) */}
      <div className="flex items-center justify-between gap-3">
        <NewsTagChips
          activeTag={newsTagFilter}
          onTagChange={setNewsTagFilter}
          availableGroups={availableGroups}
        />
        <NewsTimeRange
          activeRange={newsTimeRange}
          onRangeChange={setNewsTimeRange}
        />
      </div>

      {/* Sentiment stats bar */}
      <SentimentStatsBar news={timeFiltered} />

      {/* Results header */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-fin-text">
          {newsSubTab === 'stock' && `${ticker ?? '个股'} 相关新闻`}
          {newsSubTab === 'market' && '市场快讯'}
          {newsSubTab === 'breaking' && '重大事件'}
          <span className="ml-2 text-xs text-fin-muted font-normal">
            ({timeFiltered.length})
          </span>
        </h3>
      </div>

      {/* News list */}
      {timeFiltered.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-32 text-fin-muted text-sm gap-1">
          {newsSubTab === 'breaking' ? (
            <>
              <span className="text-lg">✅</span>
              <span>近期无重大事件</span>
            </>
          ) : (
            <span>
              暂无匹配的新闻
              {newsTagFilter !== '全部' && ` (${newsTagFilter})`}
              {newsTimeRange !== '30d' && ` · ${newsTimeRange}内`}
            </span>
          )}
        </div>
      ) : (
        <div className="space-y-2 max-h-[600px] overflow-y-auto pr-1">
          {timeFiltered.map((news) => (
            <NewsCard
              key={`${news.title}-${news.source}-${news.ts}`}
              news={news}
              ticker={ticker ?? undefined}
              isSelected={activeSelections.some(
                (s) => s.id === generateNewsId(news.title, news.source, news.ts),
              )}
              onToggleSelect={handleToggleSelect}
              onAskAbout={handleAskAbout}
              onAnalyze={handleAnalyze}
              isAnalyzing={isAnalyzing}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default NewsTab;
