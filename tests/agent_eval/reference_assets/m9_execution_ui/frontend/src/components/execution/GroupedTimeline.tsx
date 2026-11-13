import { useMemo } from 'react';
import { Clock3 } from 'lucide-react';

import type { TimelineEvent } from '../../types/execution';
import { executionSubjectLabel, formatTimelineTime, isTimelineError, summarizeTimelineEvent } from './timelineUtils';

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
  if (event.agent || event.tool || event.name) return executionSubjectLabel(event.agent || event.tool || event.name!);
  if (event.stepId) return `步骤 ${event.stepId}`;
  if (event.parallelGroup) return `并行组 ${event.parallelGroup}`;
  if (event.eventType === 'pipeline_stage') return executionSubjectLabel(event.stage);
  return event.eventType || 'event';
}

function resolveGroupStatus(event: TimelineEvent): TimelineGroup['status'] {
  if (isTimelineError(event)) return 'error';
  if (event.eventType.endsWith('_done') || event.status === 'done') return 'done';
  if (event.eventType.endsWith('_start') || event.status === 'running') return 'running';
  return 'pending';
}

function badgeClass(status: TimelineGroup['status']): string {
  if (status === 'done') return 'text-emerald-600 dark:text-emerald-400';
  if (status === 'error') return 'text-red-600 dark:text-red-400';
  if (status === 'running') return 'text-t-info';
  return 'text-t-text2';
}

const STATUS_LABELS = { done: '完成', error: '失败', running: '进行中', pending: '等待中' };

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
      .map((group) => {
        const unique = new Map<string, TimelineEvent>();
        group.events.forEach((event) => unique.set(summarizeTimelineEvent(event), event));
        return { ...group, events: [...unique.values()].slice(compact ? -2 : -4) };
      });
  }, [timeline, maxGroups, compact]);

  if (!groups.length) {
    return (
      <div className="py-3 text-sm text-t-text2">
        暂无执行时间线
      </div>
    );
  }

  return (
    <section className="border-t border-t-divider pt-4">
      <h3 className="flex items-center gap-2 text-sm font-medium text-t-text">
        <Clock3 size={16} className="text-t-text2" />
        分组时间线
      </h3>
      <div className="mt-2 divide-y divide-t-divider">
        {groups.map((group) => (
          <div key={group.key} className="py-3">
            <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
              <div className="min-w-0 break-words text-sm font-medium text-t-text">{group.title}</div>
              <div className="flex shrink-0 items-center gap-3">
                <span className={`text-xs ${badgeClass(group.status)}`}>
                  {STATUS_LABELS[group.status]}
                </span>
                <time className="num text-xs text-t-text2" dateTime={group.updatedAt}>{formatTimelineTime(group.updatedAt)}</time>
              </div>
            </div>
            <div className="mt-1 space-y-1">
              {group.events.map((event) => (
                <div key={event.id} className="break-words text-xs leading-relaxed text-t-text2">
                  {summarizeTimelineEvent(event)}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

export default GroupedTimeline;
