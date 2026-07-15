import { ExternalLink, Radio } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import {
  useMonitorCommentFeed,
  type MonitorComment,
} from '../../hooks/useMonitorCommentFeed';

type FeedItem =
  | { kind: 'comment'; comment: MonitorComment }
  | { kind: 'heartbeat'; id: string; from: string; to: string; count: number };

// eslint-disable-next-line react-refresh/only-export-components -- 纯折叠策略需要独立单测
export function foldHeartbeatComments(comments: MonitorComment[]): FeedItem[] {
  const result: FeedItem[] = [];
  let group: MonitorComment[] = [];
  const flush = () => {
    if (!group.length) return;
    const newest = group[0];
    const oldest = group[group.length - 1];
    result.push({
      kind: 'heartbeat',
      id: `heartbeat:${newest.id}`,
      from: oldest.ts,
      to: newest.ts,
      count: group.length,
    });
    group = [];
  };
  for (const comment of comments) {
    if (comment.level === 'info' && comment.trigger.kind === 'heartbeat') {
      group.push(comment);
    } else {
      flush();
      result.push({ kind: 'comment', comment });
    }
  }
  flush();
  return result;
}

const formatTime = (value: string) => new Date(value).toLocaleTimeString('zh-CN', {
  hour: '2-digit',
  minute: '2-digit',
});

type MonitorActivityFeedProps = {
  sessionId: string | null | undefined;
  symbol: string;
};

export function MonitorActivityFeed({ sessionId, symbol }: MonitorActivityFeedProps) {
  const navigate = useNavigate();
  const { comments, error, isAvailable, unavailable } = useMonitorCommentFeed(sessionId, symbol);
  const items = foldHeartbeatComments(comments);
  const storageKey = `finsight:monitor-comment-seen:${sessionId || 'none'}:${symbol.toUpperCase()}`;
  const [seenIds, setSeenIds] = useState<Set<string>>(new Set());

  useEffect(() => {
    try {
      setSeenIds(new Set(JSON.parse(sessionStorage.getItem(storageKey) || '[]') as string[]));
    } catch {
      setSeenIds(new Set());
    }
  }, [storageKey]);

  const alertCount = useMemo(
    () => comments.filter((item) => item.level === 'alert' && !seenIds.has(item.id)).length,
    [comments, seenIds],
  );

  const markSeen = (id: string) => {
    setSeenIds((previous) => {
      const next = new Set(previous).add(id);
      try {
        sessionStorage.setItem(storageKey, JSON.stringify([...next]));
      } catch {
        // sessionStorage 不可写时只保留本页状态。
      }
      return next;
    });
  };

  return (
    <section
      className="shrink-0 border-y border-fin-border bg-fin-bg/40"
      data-testid="monitor-activity-feed"
      aria-label={`${symbol} AI 动态`}
    >
      <div className="flex min-h-9 items-center justify-between gap-3 px-5 max-lg:px-3">
        <div className="flex min-w-0 items-center gap-2 text-xs font-medium text-fin-text">
          <Radio size={13} className="shrink-0 text-fin-primary" />
          <span>AI 动态</span>
          <span className="truncate text-2xs font-normal text-fin-muted">{symbol.toUpperCase()}</span>
          {alertCount > 0 && (
            <span className="shrink-0 text-2xs text-fin-danger">未读 {alertCount}</span>
          )}
        </div>
        {!isAvailable && <span className="shrink-0 text-2xs text-fin-muted">登录后启用</span>}
        {isAvailable && unavailable && (
          <span className="shrink-0 text-2xs text-fin-danger">实时点评服务不可用</span>
        )}
        {isAvailable && error && !unavailable && (
          <span className="shrink-0 text-2xs text-fin-danger">连接中断，正在重试</span>
        )}
      </div>

      {items.length === 0 ? (
        <div className="flex min-h-11 items-center px-5 pb-2 text-2xs text-fin-muted max-lg:px-3">
          {unavailable
            ? '实时点评存储当前不可访问。'
            : isAvailable
              ? '等待当前标的的确定性触发。'
              : '匿名模式不会启动实时 AI 监控。'}
        </div>
      ) : (
        <div className="max-h-36 overflow-y-auto border-t border-fin-border/70">
          {items.map((item) => item.kind === 'heartbeat' ? (
            <div
              key={item.id}
              className="flex min-h-8 items-center px-5 text-2xs text-fin-muted max-lg:px-3"
            >
              {formatTime(item.from)}-{formatTime(item.to)} 无显著变化 x{item.count}
            </div>
          ) : (
            <div
              key={item.comment.id}
              className="grid min-h-12 grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-2 border-b border-fin-border/60 px-5 py-2 text-xs last:border-b-0 max-lg:px-3"
              onClick={() => markSeen(item.comment.id)}
            >
              <span className={[
                'mt-0.5 text-2xs font-semibold',
                item.comment.level === 'alert' || item.comment.level === 'error'
                  ? 'text-fin-danger'
                  : 'text-fin-primary',
              ].join(' ')}>
                {item.comment.level.toUpperCase()}
              </span>
              <div className="min-w-0">
                <p className="break-words text-fin-text-secondary">{item.comment.text}</p>
                <p className="mt-0.5 truncate text-2xs text-fin-muted">
                  {item.comment.escalated ? '已触发 Prediction 重估 · ' : ''}
                  {item.comment.trigger.detail}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-2xs text-fin-muted">{formatTime(item.comment.ts)}</span>
                {item.comment.chart_url && (
                  <button
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      markSeen(item.comment.id);
                      navigate(item.comment.chart_url!);
                    }}
                    className="inline-flex size-7 items-center justify-center text-fin-primary hover:text-fin-text"
                    title="查看关联 Prediction"
                    aria-label="查看关联 Prediction"
                  >
                    <ExternalLink size={13} />
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

export default MonitorActivityFeed;
