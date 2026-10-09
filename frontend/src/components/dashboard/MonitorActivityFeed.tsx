import { AlertCircle, AlertTriangle, ExternalLink, Info, Radio } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import {
  useMonitorCommentFeed,
  type MonitorComment,
} from '../../hooks/useMonitorCommentFeed';
import { useMonitorLease } from '../../hooks/useMonitorLease';

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
    // 旧版本曾把心跳写成 error，但它的触发语义仍是“无显式触发”。
    // 以触发类型为准，避免历史记录被渲染成点评失败。
    if (comment.trigger.kind === 'heartbeat') {
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

const LEVELS = {
  info: { label: '动态', Icon: Info, tone: 'text-t-info' },
  warn: { label: '注意', Icon: AlertTriangle, tone: 'text-t-warning' },
  alert: { label: '提醒', Icon: AlertTriangle, tone: 'text-t-warning' },
  error: { label: '异常', Icon: AlertCircle, tone: 'text-t-down' },
} as const;

type MonitorActivityFeedProps = {
  sessionId: string | null | undefined;
  symbol: string;
};

export function MonitorActivityFeed({ sessionId, symbol }: MonitorActivityFeedProps) {
  const navigate = useNavigate();
  const { comments, error, isAvailable, unavailable, workState } = useMonitorCommentFeed(sessionId, symbol);
  const leaseStatus = useMonitorLease(symbol);
  const statusText = !isAvailable ? '登录后启用'
    : leaseStatus === 'error' ? '监控未启动：租约连接失败'
    : leaseStatus === 'stopped' ? '监控已停止'
    : unavailable ? '实时点评服务不可用'
    : error ? '连接中断'
    : workState?.status === 'degraded' ? '缺少盘中快照，实时触发暂停'
    : workState?.status === 'closed' ? '当前市场休市'
    : workState?.status === 'disabled' ? '实时监控未启用'
    : workState?.status === 'error' ? '监控运行异常'
    : workState?.status === 'running' ? '等待当前标的的确定性触发'
    : '监控启动中';
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
      className="shrink-0 border-b border-t-divider bg-t-bg"
      data-testid="monitor-activity-feed"
      aria-label={`${symbol} AI 动态`}
    >
      <div className="flex min-h-12 flex-wrap items-center justify-between gap-x-3 gap-y-1 px-6 py-2 max-lg:px-4">
        <div className="flex min-w-0 items-center gap-2 text-sm font-medium text-t-text">
          <Radio size={16} className="shrink-0 text-t-text3" />
          <span>AI 动态</span>
          <span className="truncate text-xs font-normal text-t-text3">{symbol.toUpperCase()}</span>
          {alertCount > 0 && (
            <span className="shrink-0 text-xs text-t-warning">未读 {alertCount}</span>
          )}
        </div>
        <span className="text-xs text-t-text3">{statusText}</span>
      </div>

      {items.length === 0 ? (
        <div className="flex min-h-11 items-center px-6 pb-3 text-sm text-t-text3 max-lg:px-4">
          {statusText}
        </div>
      ) : (
        <div className="max-h-48 overflow-y-auto">
          {items.map((item) => {
            if (item.kind === 'heartbeat') return (
            <div
              key={item.id}
              className="flex min-h-9 items-center px-6 py-2 text-xs text-t-text3 max-lg:px-4"
            >
              {formatTime(item.from)}–{formatTime(item.to)} 无显著变化 · {item.count} 次检查
            </div>
            );
            const level = LEVELS[item.comment.level];
            const isError = item.comment.level === 'error';
            return (
            <div
              key={item.comment.id}
              className="grid grid-cols-[20px_minmax(0,1fr)_auto] items-start gap-x-3 gap-y-1 border-b border-t-divider/70 px-6 py-3 last:border-b-0 max-lg:px-4"
              onClick={() => markSeen(item.comment.id)}
            >
              <span className={`mt-1 ${level.tone}`} title={level.label}>
                <level.Icon size={17} aria-label={level.label} />
              </span>
              <div className="min-w-0">
                <p className="break-words text-sm leading-6 text-t-text2">{isError ? '实时点评生成失败，本次未产生新判断。' : item.comment.text}</p>
                {isError && (
                  <details className="mt-1 text-xs text-t-text3">
                    <summary className="cursor-pointer py-1 hover:text-t-text2">错误详情</summary>
                    <p className="break-words py-1 leading-5">{item.comment.text}</p>
                  </details>
                )}
                <p className="mt-1 break-words text-xs leading-5 text-t-text3">
                  {item.comment.escalated ? '已触发 AI 判断重估 · ' : ''}
                  {item.comment.trigger.detail}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <span className="tabular-nums text-xs leading-6 text-t-text3">{formatTime(item.comment.ts)}</span>
                {item.comment.chart_url && (
                  <button
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      markSeen(item.comment.id);
                      navigate(item.comment.chart_url!);
                    }}
                    className="inline-flex size-9 items-center justify-center rounded text-t-info hover:bg-t-hover hover:text-t-text"
                    title="查看关联 AI 判断"
                    aria-label="查看关联 AI 判断"
                  >
                    <ExternalLink size={15} />
                  </button>
                )}
              </div>
            </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

export default MonitorActivityFeed;
