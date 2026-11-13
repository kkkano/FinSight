import { useState } from 'react';
import { Check, Copy, X } from 'lucide-react';
import type { ConsoleEvent } from './eventModel';
import { eventColor, formatSize, formatTs } from './eventModel';
import { serializeEvents } from './AgentLogExport';

interface AgentEventRowProps {
  event: ConsoleEvent;
  isSelected: boolean;
  onClick: () => void;
}

export function AgentEventRow({ event, isSelected, onClick }: AgentEventRowProps) {
  return <button type="button" onClick={onClick} aria-pressed={isSelected}
    className={`flex w-full items-start gap-2 border-b border-t-border/30 px-2 py-1.5 text-left text-2xs ${isSelected ? 'bg-t-accent/10' : 'hover:bg-t-hover'}`}>
    <span className="num shrink-0 text-t-text3">{event.frame.seq ?? '—'}</span>
    <time className="num shrink-0 text-t-text3" dateTime={event.timestamp}>{formatTs(event.timestamp)}</time>
    <span className="min-w-0 flex-1">
      <span className={`block break-words ${eventColor(event)}`}>{event.frame.type} · {event.agentLabel}</span>
      <span className="block truncate text-t-text" title={event.summary}>{event.summary}</span>
    </span>
    <span className="num shrink-0 text-t-text3">{formatSize(event.size)}</span>
  </button>;
}

export function EventDetail({ event, onClose }: { event: ConsoleEvent; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  const json = serializeEvents([event]);
  const copy = async () => {
    await navigator.clipboard.writeText(json);
    setCopied(true);
  };
  return <section aria-label="事件详情" className="flex h-full min-h-0 flex-col text-2xs">
    <div className="flex items-center justify-between gap-2 border-b border-t-border bg-t-bg px-2 py-1.5">
      <span className="truncate text-t-text2">{event.frame.type}</span>
      <div className="flex items-center gap-2">
        <button type="button" onClick={() => void copy()} title="复制事件JSON" className="text-t-text3 hover:text-t-text">
          {copied ? <Check size={13} className="text-t-success" /> : <Copy size={13} />}
        </button>
        <button type="button" onClick={onClose} title="关闭事件详情" className="text-t-text3 hover:text-t-text"><X size={13} /></button>
      </div>
    </div>
    <pre className="min-h-0 flex-1 overflow-auto whitespace-pre-wrap break-all p-2 font-mono text-2xs text-t-text2">{json}</pre>
  </section>;
}
