import { ExternalLink, Radio } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMonitorCommentFeed, type MonitorComment } from '../../hooks/useMonitorCommentFeed';

type FeedItem = { kind: 'comment'; comment: MonitorComment } | {
  kind: 'heartbeat'; id: string; from: string; to: string; count: number;
};

// eslint-disable-next-line react-refresh/only-export-components -- 纯折叠策略需要独立单测
export function foldHeartbeatComments(comments: MonitorComment[]): FeedItem[] {
  const result: FeedItem[] = [];
  let group: MonitorComment[] = [];
  const flush = () => {
    if (!group.length) return;
    const newest = group[0];
    const oldest = group[group.length - 1];
    result.push({ kind: 'heartbeat', id: `heartbeat:${newest.id}`, from: oldest.ts, to: newest.ts, count: group.length });
    group = [];
  };
  for (const comment of comments) {
    if (comment.level === 'info' && comment.trigger.kind === 'heartbeat') group.push(comment);
    else {
      flush();
      result.push({ kind: 'comment', comment });
    }
  }
  flush();
  return result;
}

const time = (value: string) => new Date(value).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });

export function MonitorCommentFeed({ sessionId }: { sessionId: string | null | undefined }) {
  const navigate = useNavigate();
  const { comments, error } = useMonitorCommentFeed(sessionId);
  const items = foldHeartbeatComments(comments);
  const storageKey = `finsight:monitor-comment-seen:${sessionId || 'none'}`;
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
      try { sessionStorage.setItem(storageKey, JSON.stringify([...next])); } catch { /* best effort */ }
      return next;
    });
  };

  return (
    <div className="border-b border-fin-border bg-fin-bg/40 px-3 py-3" data-testid="monitor-comment-feed">
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-2 text-xs font-medium text-fin-text">
          <Radio size={13} className="text-fin-primary" /> 实时点评
          {alertCount > 0 && <span className="rounded-full bg-fin-danger/10 px-1.5 py-0.5 text-2xs text-fin-danger">未读警报 {alertCount}</span>}
        </div>
        {error && <span className="text-2xs text-fin-danger">连接已中断</span>}
      </div>
      {items.length === 0 ? (
        <div className="text-2xs text-fin-muted">打开看板后，这里会显示可追溯的实时触发与点评。</div>
      ) : (
        <div className="max-h-64 space-y-2 overflow-y-auto">
          {items.map((item) => item.kind === 'heartbeat' ? (
            <div key={item.id} className="text-2xs text-fin-muted">
              {time(item.from)}-{time(item.to)} 无事 x{item.count}
            </div>
          ) : (
            <div key={item.comment.id} onClick={() => markSeen(item.comment.id)} className="rounded border border-fin-border bg-fin-card px-2.5 py-2 text-xs">
              <div className="flex items-center justify-between gap-2">
                <span className={`font-medium ${item.comment.level === 'alert' || item.comment.level === 'error' ? 'text-fin-danger' : 'text-fin-text'}`}>
                  {item.comment.level.toUpperCase()} · {item.comment.source === 'agent' ? 'Agent' : 'System'}
                  {item.comment.escalated ? ' · 已升级' : ''}
                </span>
                <span className="text-2xs text-fin-muted">{time(item.comment.ts)}</span>
              </div>
              <p className="mt-1 text-fin-text-secondary">{item.comment.text}</p>
              <p className="mt-1 text-2xs text-fin-muted">触发：{item.comment.trigger.detail}</p>
              {item.comment.chart_url && (
                <button type="button" onClick={() => navigate(item.comment.chart_url!)} className="mt-2 inline-flex min-h-8 items-center gap-1 text-2xs text-fin-primary hover:underline">
                  查看图表 <ExternalLink size={11} />
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
