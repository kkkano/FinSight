import { useMemo } from 'react';
import { Clock3 } from 'lucide-react';

import type { TimelineEvent } from '../../types/execution';
import { formatTimelineTime, isTimelineError, summarizeTimelineEvent } from './timelineUtils';

type TimelineGroup = {
  key: string;
  title: string;
  status: 'running' | 'done' | 'error' | 'pending';
  updatedAt: string;
  events: TimelineEvent[];
};

type GroupedTimelineProps = {
  timeline: TimelineEvent[];
  maxGroups?: number;
  compact?: boolean;
};

function resolveGroupKey(event: TimelineEvent): string {
  if (event.stepId) return `step:${event.stepId}`;
  if (event.agent) return `agent:${event.agent}`;
  if (event.parallelGroup) return `group:${event.parallelGroup}`;
  if (event.eventType === 'pipeline_stage') return `pipeline:${event.stage}`;
  return `event:${event.eventType}`;
}

function resolveGroupTitle(event: TimelineEvent): string {
  if (event.stepId) return `Step ${event.stepId}`;
  if (event.agent) return `Agent ${event.agent}`;
  if (event.parallelGroup) return `Parallel ${event.parallelGroup}`;
  if (event.eventType === 'pipeline_stage') return `Stage ${event.stage}`;
  return event.eventType || 'event';
}

function resolveGroupStatus(event: TimelineEvent): TimelineGroup['status'] {
  if (isTimelineError(event)) return 'error';
  if (event.eventType.endsWith('_done') || event.status === 'done') return 'done';
  if (event.eventType.endsWith('_start') || event.status === 'running') return 'running';
  return 'pending';
}

function badgeClass(status: TimelineGroup['status']): string {
  if (status === 'done') return 'bg-emerald-500/15 text-emerald-300';
  if (status === 'error') return 'bg-red-500/15 text-red-300';
  if (status === 'running') return 'bg-blue-500/15 text-blue-300';
  return 'bg-fin-border/60 text-fin-muted';
}

export function GroupedTimeline({
  timeline,
  maxGroups = 10,
  compact = false,
}: GroupedTimelineProps) {
  const groups = useMemo(() => {
    const bucket = new Map<string, TimelineGroup>();
    const recent = timeline.slice(-120);

    for (const event of recent) {
      const key = resolveGroupKey(event);
      const existing = bucket.get(key);
      if (!existing) {
        bucket.set(key, {
          key,
          title: resolveGroupTitle(event),
          status: resolveGroupStatus(event),
          updatedAt: event.timestamp,
          events: [event],
        });
        continue;
      }

      existing.events.push(event);
      existing.updatedAt = event.timestamp;
      const nextStatus = resolveGroupStatus(event);
      if (nextStatus === 'error' || nextStatus === 'done' || nextStatus === 'running') {
        existing.status = nextStatus;
      }
    }

    return Array.from(bucket.values())
      .sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt))
      .slice(0, maxGroups)
      .map((group) => ({
        ...group,
        events: group.events.slice(-4),
      }));
  }, [timeline, maxGroups]);

  if (!groups.length) {
    return (
      <div className="rounded-lg border border-fin-border bg-fin-bg/20 px-3 py-3 text-xs text-fin-muted">
        暂无执行时间线
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-fin-border bg-fin-bg/20">
      <div className="flex items-center gap-1.5 px-3 py-2 border-b border-fin-border/60 text-xs text-fin-text-secondary">
        <Clock3 size={12} />
        分组时间线
      </div>
      <div className={`${compact ? 'max-h-48' : 'max-h-72'} overflow-y-auto divide-y divide-fin-border/40`}>
        {groups.map((group) => (
          <div key={group.key} className="px-3 py-2">
            <div className="flex items-center justify-between gap-2">
              <div className="text-xs text-fin-text font-medium truncate">{group.title}</div>
              <div className="flex items-center gap-2 shrink-0">
                <span className={`px-1.5 py-0.5 rounded text-2xs ${badgeClass(group.status)}`}>
                  {group.status}
                </span>
                <span className="text-2xs text-fin-muted">{formatTimelineTime(group.updatedAt)}</span>
              </div>
            </div>
            <div className="mt-1 space-y-1">
              {group.events.map((event) => (
                <div key={event.id} className="text-2xs text-fin-muted leading-relaxed">
                  {summarizeTimelineEvent(event)}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default GroupedTimeline;

