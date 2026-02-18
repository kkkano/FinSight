import { useMemo, useState } from 'react';
import { ChevronDown, ChevronUp, Clock3 } from 'lucide-react';

import type { TimelineEvent } from '../../types/execution';
import {
  formatTimelineTime,
  summarizeTimelineEvent,
  isTimelineError,
} from './timelineUtils';

interface AgentTimelineProps {
  timeline: TimelineEvent[];
  compact?: boolean;
  defaultExpanded?: boolean;
  maxVisible?: number;
}

export function AgentTimeline({
  timeline,
  compact = false,
  defaultExpanded = false,
  maxVisible = 80,
}: AgentTimelineProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  const visibleEvents = useMemo(() => {
    if (!expanded) return [];
    if (timeline.length <= maxVisible) return timeline;
    return timeline.slice(timeline.length - maxVisible);
  }, [expanded, timeline, maxVisible]);

  if (!timeline.length) return null;

  return (
    <div className="border border-fin-border rounded-lg bg-fin-bg/40">
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        className="w-full flex items-center justify-between px-3 py-2 text-xs text-fin-text-secondary hover:text-fin-text transition-colors"
      >
        <span className="flex items-center gap-1.5">
          <Clock3 size={12} />
          Agent Timeline ({timeline.length})
        </span>
        {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
      </button>

      {expanded && (
        <div className={`${compact ? 'max-h-40' : 'max-h-64'} overflow-y-auto border-t border-fin-border/60`}>
          <ul className="divide-y divide-fin-border/40">
            {visibleEvents.map((event) => (
              <li key={event.id} className="px-3 py-2 text-2xs">
                <div className="flex items-center justify-between gap-2">
                  <span className={`${isTimelineError(event) ? 'text-red-400' : 'text-fin-text-secondary'}`}>
                    {summarizeTimelineEvent(event)}
                  </span>
                  <span className="text-fin-muted shrink-0">
                    {formatTimelineTime(event.timestamp)}
                  </span>
                </div>
                {(event.agent || event.tool || event.durationMs !== undefined) && (
                  <div className="mt-1 text-fin-muted flex items-center gap-2">
                    {event.agent && <span>agent: {event.agent}</span>}
                    {event.tool && <span>tool: {event.tool}</span>}
                    {event.durationMs !== undefined && <span>{event.durationMs}ms</span>}
                    {event.cached && <span>cached</span>}
                    {event.skipped && <span>skipped</span>}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export default AgentTimeline;

