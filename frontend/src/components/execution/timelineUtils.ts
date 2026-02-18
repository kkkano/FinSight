import type { TimelineEvent } from '../../types/execution';

export function formatTimelineTime(iso?: string): string {
  if (!iso) return '--:--:--';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '--:--:--';
  return date.toLocaleTimeString();
}

export function summarizeTimelineEvent(event: TimelineEvent): string {
  if (event.message) return event.message;

  if (event.eventType === 'step_start') {
    return `${event.kind || 'step'} ${event.name || event.stepId || ''} started`.trim();
  }
  if (event.eventType === 'step_done') {
    const suffix = event.cached ? ' (cached)' : event.skipped ? ' (skipped)' : '';
    return `${event.kind || 'step'} ${event.name || event.stepId || ''} done${suffix}`.trim();
  }
  if (event.eventType === 'tool_start') {
    return `tool ${event.tool || event.name || ''} started`.trim();
  }
  if (event.eventType === 'tool_end') {
    return `tool ${event.tool || event.name || ''} done`.trim();
  }
  if (event.eventType === 'agent_start') {
    return `agent ${event.agent || event.name || ''} started`.trim();
  }
  if (event.eventType === 'agent_done') {
    return `agent ${event.agent || event.name || ''} done`.trim();
  }
  if (event.eventType === 'agent_error') {
    return `agent ${event.agent || event.name || ''} error`.trim();
  }

  return event.stage || event.eventType || 'event';
}

export function isTimelineError(event: TimelineEvent): boolean {
  return event.eventType === 'error' || event.eventType === 'agent_error' || event.stage === 'error';
}

