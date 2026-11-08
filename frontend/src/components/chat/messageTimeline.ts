import type { ThinkingStep } from '../../types';
import type { ResearchBlock } from '../../types/runtime';
import { buildTurnActivities, type Activity } from './TurnActivity';

export type MessageTimelineItem = { kind: 'block'; block: ResearchBlock; seq: number }
  | { kind: 'activity'; rows: Activity[]; seq: number };

/** 使用服务端事件顺序；旧消息没有seq时仅保留原有活动/正文次序。 */
export function buildMessageTimeline(blocks: ResearchBlock[], thinking: ThinkingStep[], loading: boolean): MessageTimelineItem[] {
  const rows = buildTurnActivities(thinking, loading);
  const parents = new Set(rows.filter((row) => row.kind === 'agent').map((row) => row.agent).filter(Boolean));
  const items: MessageTimelineItem[] = rows.filter((row) => row.kind === 'agent' || !parents.has(row.agent)).map((row, index) => ({
    kind: 'activity', seq: row.seq ?? index - 10000,
    rows: row.kind === 'agent' ? [row, ...rows.filter((child) => child.kind !== 'agent' && child.agent === row.agent)] : [row],
  }));
  items.push(...blocks.map((block, index): MessageTimelineItem => ({ kind: 'block', block, seq: block.seq ?? index })));
  const sorted = items.sort((left, right) => left.seq - right.seq);
  return sorted.reduce<MessageTimelineItem[]>((grouped, item) => {
    const previous = grouped.at(-1);
    if (item.kind === 'activity' && previous?.kind === 'activity') previous.rows.push(...item.rows);
    else grouped.push(item);
    return grouped;
  }, []);
}
