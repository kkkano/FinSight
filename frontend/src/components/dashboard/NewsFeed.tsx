/**
 * NewsFeed 组件 - 新闻流
 *
 * 功能：
 * - 双模式切换：Market 7x24 / Impact on {symbol}
 * - 新闻列表展示
 * - 外链跳转
 * - "问这条"按钮：将新闻选中到 MiniChat 上下文
 */
import { useState } from 'react';
import { ExternalLink, Newspaper, TrendingUp, MessageCircleQuestion } from 'lucide-react';
import { useDashboardStore } from '../../store/dashboardStore';
import type { NewsItem, NewsModeType, SelectionItem } from '../../types/dashboard';
import { generateNewsId } from '../../utils/hash';

interface NewsFeedProps {
  marketNews: NewsItem[];
  impactNews: NewsItem[];
  loading?: boolean;
}

export function NewsFeed({ marketNews, impactNews, loading }: NewsFeedProps) {
  const { activeAsset, newsMode, setNewsMode } = useDashboardStore();
  const [localMode, setLocalMode] = useState<NewsModeType>(newsMode);

  // 切换模式
  const handleModeChange = (mode: NewsModeType) => {
    setLocalMode(mode);
    setNewsMode(mode);
  };

  // 当前显示的新闻
  const currentNews = localMode === 'market' ? marketNews : impactNews;

  // 格式化时间
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
      return ts.split('T')[0];
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
      {/* Header with mode toggle */}
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-fin-text">新闻动态</h3>

        {/* Mode Toggle */}
        <div className="flex bg-fin-bg-secondary rounded-lg p-0.5">
          <button
            onClick={() => handleModeChange('market')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
              localMode === 'market'
                ? 'bg-fin-card text-fin-primary shadow-sm'
                : 'text-fin-muted hover:text-fin-text'
            }`}
          >
            <Newspaper size={12} />
            Market 7x24
          </button>
          <button
            onClick={() => handleModeChange('impact')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
              localMode === 'impact'
                ? 'bg-fin-card text-fin-primary shadow-sm'
                : 'text-fin-muted hover:text-fin-text'
            }`}
          >
            <TrendingUp size={12} />
            Impact
            {activeAsset && (
              <span className="text-fin-muted">({activeAsset.symbol})</span>
            )}
          </button>
        </div>
      </div>

      {/* News List */}
      {currentNews.length === 0 ? (
        <div className="flex items-center justify-center h-32 text-fin-muted text-sm">
          {localMode === 'market' ? '暂无市场新闻' : '暂无相关新闻'}
        </div>
      ) : (
        <div className="space-y-3 max-h-64 overflow-y-auto">
          {currentNews.map((news, index) => (
            <NewsItemCard key={index} news={news} formatTime={formatTime} />
          ))}
        </div>
      )}
    </div>
  );
}

// 单条新闻卡片
interface NewsItemCardProps {
  news: NewsItem;
  formatTime: (ts: string) => string;
}

function NewsItemCard({ news, formatTime }: NewsItemCardProps) {
  const { setActiveSelection, activeSelection } = useDashboardStore();

  // 生成新闻 ID（用于比较是否已选中）
  const newsId = generateNewsId(news.title, news.source, news.ts);
  const isSelected = activeSelection?.id === newsId;

  const handleClick = () => {
    if (news.url && news.url !== '#') {
      window.open(news.url, '_blank');
    }
  };

  // 处理"问这条"按钮点击
  const handleAskAbout = (e: React.MouseEvent) => {
    e.stopPropagation(); // 阻止冒泡，避免触发卡片点击（外链跳转）

    const selection: SelectionItem = {
      type: 'news',
      id: newsId,
      title: news.title,
      url: news.url,
      source: news.source,
      ts: news.ts,
      snippet: news.summary?.slice(0, 100) || news.title.slice(0, 100),
    };

    setActiveSelection(selection);
  };

  return (
    <div
      onClick={handleClick}
      className={`group p-3 rounded-lg border transition-colors ${
        isSelected
          ? 'border-fin-primary bg-fin-primary/5'
          : 'border-transparent hover:border-fin-border hover:bg-fin-hover'
      } ${news.url && news.url !== '#' ? 'cursor-pointer' : ''}`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          {/* 标题 */}
          <h4 className="text-sm font-medium text-fin-text line-clamp-2 group-hover:text-fin-primary transition-colors">
            {news.title}
          </h4>

          {/* 摘要（如果有） */}
          {news.summary && (
            <p className="text-xs text-fin-muted mt-1 line-clamp-2">
              {news.summary}
            </p>
          )}

          {/* Meta */}
          <div className="flex items-center gap-2 mt-2 text-[10px] text-fin-muted">
            {news.source && (
              <>
                <span>{news.source}</span>
                <span>·</span>
              </>
            )}
            <span>{formatTime(news.ts)}</span>
          </div>
        </div>

        {/* 操作按钮区 */}
        <div className="flex items-center gap-1 shrink-0 mt-1">
          {/* "问这条"按钮 */}
          <button
            onClick={handleAskAbout}
            title="问这条"
            className={`p-1.5 rounded-md transition-all ${
              isSelected
                ? 'bg-fin-primary text-white'
                : 'text-fin-muted opacity-0 group-hover:opacity-100 hover:bg-fin-primary/10 hover:text-fin-primary'
            }`}
          >
            <MessageCircleQuestion size={14} />
          </button>

          {/* 外链图标 */}
          {news.url && news.url !== '#' && (
            <ExternalLink
              size={14}
              className="text-fin-muted opacity-0 group-hover:opacity-100 transition-opacity"
            />
          )}
        </div>
      </div>
    </div>
  );
}

export default NewsFeed;
