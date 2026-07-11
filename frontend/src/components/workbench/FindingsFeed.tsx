/**
 * FindingsFeed.tsx —— 发现流（工作台核心区）
 *
 * 顶部：标题「今日发现」+ 筛选 tab（全部 / 未读）+「立即扫描」按钮（loading 态）。
 * 列表：FindingCard[]，按未读优先 + 时间倒序（由 useFindings 排序）。
 * 空状态：引导文案，告诉用户 agent 正在盯盘。
 * 轮询：useFindings 内部每 60 秒自动刷新，组件卸载时清理。
 */
import { useMemo, useState } from 'react';
import { Loader2, RadarIcon, RefreshCw } from 'lucide-react';

import { useFindings } from '../../hooks/useFindings';
import { EmptyState } from '../ui';
import { FindingCard } from './FindingCard';

interface FindingsFeedProps {
  sessionId: string | null | undefined;
  /** 行动按钮跳转 Chat 深挖 */
  onNavigateToChat?: (ticker: string) => void;
  /** 行动按钮联动调仓卡片（滚动 + 高亮） */
  onNavigateToRebalance?: () => void;
}

type FeedFilter = 'all' | 'unread';

export function FindingsFeed({
  sessionId,
  onNavigateToChat,
  onNavigateToRebalance,
}: FindingsFeedProps) {
  const { findings, loading, error, scanning, scan, markViewed } = useFindings(sessionId);
  const [filter, setFilter] = useState<FeedFilter>('all');

  const unreadCount = useMemo(
    () => findings.filter((f) => f.status === 'new').length,
    [findings],
  );

  const visibleFindings = useMemo(
    () => (filter === 'unread' ? findings.filter((f) => f.status === 'new') : findings),
    [filter, findings],
  );

  return (
    <div className="bg-fin-card border border-fin-border rounded-lg overflow-hidden">
      {/* 头部 */}
      <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-fin-border bg-gradient-to-r from-fin-primary/5 to-transparent flex-wrap">
        <div className="flex items-center gap-2">
          <span className="inline-flex h-7 w-7 items-center justify-center rounded-lg bg-fin-primary/10 text-fin-primary">
            <RadarIcon size={15} />
          </span>
          <span className="text-sm font-semibold text-fin-text">今日发现</span>
          {unreadCount > 0 && (
            <span className="px-1.5 py-0.5 rounded-full text-2xs font-medium bg-fin-primary/10 text-fin-primary">
              {unreadCount} 条未读
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          {/* 筛选 tab */}
          <div className="flex items-center rounded-lg border border-fin-border overflow-hidden">
            <button
              type="button"
              onClick={() => setFilter('all')}
              data-testid="findings-filter-all"
              className={`px-2.5 py-1 text-xs transition-colors ${
                filter === 'all'
                  ? 'bg-fin-primary/10 text-fin-primary'
                  : 'text-fin-muted hover:text-fin-text'
              }`}
            >
              全部
            </button>
            <button
              type="button"
              onClick={() => setFilter('unread')}
              data-testid="findings-filter-unread"
              className={`px-2.5 py-1 text-xs transition-colors border-l border-fin-border ${
                filter === 'unread'
                  ? 'bg-fin-primary/10 text-fin-primary'
                  : 'text-fin-muted hover:text-fin-text'
              }`}
            >
              未读
            </button>
          </div>

          {/* 立即扫描 */}
          <button
            type="button"
            onClick={() => void scan()}
            disabled={scanning || !sessionId}
            data-testid="findings-scan-button"
            className="flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-lg bg-fin-primary/10 text-fin-primary hover:bg-fin-primary/20 hover:shadow-sm disabled:opacity-50 disabled:cursor-not-allowed transition-all"
          >
            {scanning ? (
              <Loader2 size={13} className="animate-spin" />
            ) : (
              <RefreshCw size={13} />
            )}
            立即扫描
          </button>
        </div>
      </div>

      {/* 错误提示 */}
      {error && (
        <div
          className="px-4 py-2.5 text-xs text-fin-danger bg-fin-danger/10 border-b border-fin-border"
          data-testid="findings-error"
        >
          {error}
        </div>
      )}

      {/* 列表 / 空状态 */}
      <div className="p-3 space-y-2.5">
        {loading && findings.length === 0 ? (
          <div className="py-8 text-center text-xs text-fin-muted" data-testid="findings-loading">
            正在加载发现流...
          </div>
        ) : visibleFindings.length === 0 ? (
          <EmptyState
            icon={RadarIcon}
            message={filter === 'unread'
              ? '没有未读发现，Agent 盯盘正常。'
              : 'Agent 正在盯盘，当前没有价格异动或集中度风险。'}
            action={filter === 'unread'
              ? { label: '查看全部发现', onClick: () => setFilter('all') }
              : { label: '立即扫描', onClick: () => void scan() }}
            className="py-10"
          />
        ) : (
          visibleFindings.map((finding) => (
            <FindingCard
              key={finding.id}
              finding={finding}
              onView={markViewed}
              onNavigateToChat={onNavigateToChat}
              onNavigateToRebalance={onNavigateToRebalance}
            />
          ))
        )}
      </div>
    </div>
  );
}

export default FindingsFeed;
