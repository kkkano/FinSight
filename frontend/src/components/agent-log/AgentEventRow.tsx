import { useState } from 'react';
import { Copy, Check, X } from 'lucide-react';
import type { RawSSEEvent, TraceViewMode } from '../../types';
import {
  EVENT_TYPE_CONFIG,
  formatTs,
  formatSize,
  getEventSummaryByMode,
} from './constants';

// --- JSON syntax highlighting ---

const SyntaxHighlight: React.FC<{ json: string }> = ({ json }) => {
  const highlighted = json
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"([^"]+)"(?=\s*:)/g, '<span class="text-purple-300">"$1"</span>')       // keys
    .replace(/:\s*"([^"]*)"/g, ': <span class="text-green-300">"$1"</span>')           // string values
    .replace(/:\s*(\d+\.?\d*)/g, ': <span class="text-amber-300">$1</span>')           // numbers
    .replace(/:\s*(true|false)/g, ': <span class="text-blue-300">$1</span>')            // booleans
    .replace(/:\s*(null)/g, ': <span class="text-fin-muted">$1</span>');                 // null

  return (
    <pre
      className="text-[11px] leading-relaxed whitespace-pre-wrap break-all font-mono"
      dangerouslySetInnerHTML={{ __html: highlighted }}
    />
  );
};

// --- Collapsible JSON block ---

const JsonBlock: React.FC<{ data: unknown; label?: string; defaultExpanded?: boolean }> = ({
  data,
  label,
  defaultExpanded = false,
}) => {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const [copied, setCopied] = useState(false);
  const jsonStr = JSON.stringify(data, null, 2);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(jsonStr);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="border border-fin-border rounded-md overflow-hidden my-1">
      <div
        className="flex items-center justify-between px-2 py-1 bg-fin-bg cursor-pointer hover:bg-fin-hover"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-2 text-2xs">
          <span className="text-fin-muted">{expanded ? '\u25bc' : '\u25b6'}</span>
          {label && <span className="text-fin-text-secondary font-medium">{label}</span>}
          {!expanded && (
            <span className="text-fin-muted truncate max-w-xs">
              {jsonStr.slice(0, 60)}{jsonStr.length > 60 ? '...' : ''}
            </span>
          )}
        </div>
        <button
          onClick={(e) => { e.stopPropagation(); handleCopy(); }}
          className="p-0.5 text-fin-muted hover:text-fin-text"
          title="Copy JSON"
        >
          {copied ? <Check size={10} className="text-fin-success" /> : <Copy size={10} />}
        </button>
      </div>
      {expanded && (
        <div className="p-2 bg-fin-panel max-h-[300px] overflow-auto scrollbar-thin">
          <SyntaxHighlight json={jsonStr} />
        </div>
      )}
    </div>
  );
};

// --- Single event row in list ---

export interface AgentEventRowProps {
  event: RawSSEEvent;
  isSelected: boolean;
  onClick: () => void;
  showTokens: boolean;
  index: number;
  traceViewMode: TraceViewMode;
}

export const AgentEventRow: React.FC<AgentEventRowProps> = ({
  event,
  isSelected,
  onClick,
  showTokens,
  index,
  traceViewMode,
}) => {
  const config = EVENT_TYPE_CONFIG[event.eventType] || EVENT_TYPE_CONFIG.any;

  // Token events hidden by default
  if (event.eventType === 'token' && !showTokens) return null;

  return (
    <div
      onClick={onClick}
      className={`
        flex items-center gap-0 px-2 py-[3px] cursor-pointer border-b border-fin-border/30
        font-mono text-[11px] leading-tight transition-colors
        ${isSelected
          ? 'bg-fin-primary/10 border-l-2 border-l-fin-primary'
          : 'hover:bg-fin-hover border-l-2 border-l-transparent'
        }
      `}
    >
      {/* Index */}
      <span className="w-8 shrink-0 text-2xs text-fin-muted text-right pr-2">{index}</span>

      {/* Timestamp */}
      <span className="w-[78px] shrink-0 text-2xs text-fin-muted font-mono">
        {formatTs(event.timestamp)}
      </span>

      {/* Event type badge */}
      <span className={`w-[50px] shrink-0 text-2xs font-bold ${config.color}`}>
        <span className={`inline-flex items-center gap-0.5 px-1 py-[1px] rounded ${config.bg}`}>
          {config.icon} {config.label}
        </span>
      </span>

      {/* Summary */}
      <span className="flex-1 truncate text-fin-text pl-2">
        {getEventSummaryByMode(event, traceViewMode)}
      </span>

      {/* Size */}
      <span className="w-12 shrink-0 text-right text-2xs text-fin-muted">
        {formatSize(event.size)}
      </span>
    </div>
  );
};

// --- Event detail panel (right pane) ---

export interface EventDetailProps {
  event: RawSSEEvent;
  onClose: () => void;
}

export const EventDetail: React.FC<EventDetailProps> = ({ event, onClose }) => {
  const [activeTab, setActiveTab] = useState<'parsed' | 'raw' | 'headers'>('parsed');
  const [copied, setCopied] = useState(false);
  const config = EVENT_TYPE_CONFIG[event.eventType] || EVENT_TYPE_CONFIG.any;

  const handleCopyAll = async () => {
    await navigator.clipboard.writeText(event.rawData);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="flex flex-col h-full bg-fin-card border-t border-fin-border">
      {/* Detail header */}
      <div className="flex items-center justify-between px-3 py-1.5 bg-fin-bg border-b border-fin-border">
        <div className="flex items-center gap-3">
          <span className={`text-2xs font-bold px-1.5 py-0.5 rounded ${config.bg} ${config.color}`}>
            {config.icon} {event.eventType}
          </span>
          <span className="text-2xs text-fin-muted">{formatTs(event.timestamp)}</span>
          <span className="text-2xs text-fin-muted">{formatSize(event.size)}</span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={handleCopyAll}
            className="p-1 text-fin-muted hover:text-fin-text rounded"
            title="Copy raw JSON"
          >
            {copied ? <Check size={12} className="text-fin-success" /> : <Copy size={12} />}
          </button>
          <button onClick={onClose} className="p-1 text-fin-muted hover:text-fin-text rounded">
            <X size={12} />
          </button>
        </div>
      </div>

      {/* Tab bar */}
      <div className="flex items-center gap-0 px-2 bg-fin-panel border-b border-fin-border">
        {(['parsed', 'raw', 'headers'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-3 py-1.5 text-[11px] font-medium border-b-2 transition-colors ${
              activeTab === tab
                ? 'border-fin-primary text-fin-primary'
                : 'border-transparent text-fin-muted hover:text-fin-text'
            }`}
          >
            {tab === 'parsed' ? 'Parsed' : tab === 'raw' ? 'Raw' : 'Meta'}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-auto p-2 scrollbar-thin">
        {activeTab === 'parsed' && (
          <div className="space-y-1">
            {Object.entries(event.parsedData).map(([key, value]) => (
              <div key={key}>
                {typeof value === 'object' && value !== null ? (
                  <JsonBlock data={value} label={key} />
                ) : (
                  <div className="flex items-start gap-2 px-2 py-0.5 text-[11px] font-mono">
                    <span className="text-fin-primary shrink-0">{key}:</span>
                    <span className={
                      typeof value === 'string'
                        ? 'text-fin-success'
                        : typeof value === 'number'
                          ? 'text-amber-400'
                          : typeof value === 'boolean'
                            ? 'text-blue-400'
                            : 'text-fin-muted'
                    }>
                      {typeof value === 'string' ? `"${value}"` : String(value)}
                    </span>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {activeTab === 'raw' && (
          <div className="bg-fin-panel rounded p-2 border border-fin-border">
            <SyntaxHighlight json={JSON.stringify(event.parsedData, null, 2)} />
          </div>
        )}

        {activeTab === 'headers' && (
          <div className="space-y-2 text-[11px] font-mono">
            <div className="grid grid-cols-[100px_1fr] gap-1 px-2">
              <span className="text-fin-muted">Event ID:</span>
              <span className="text-fin-text">{event.id}</span>

              <span className="text-fin-muted">Timestamp:</span>
              <span className="text-fin-text">{event.timestamp}</span>

              <span className="text-fin-muted">Event Type:</span>
              <span className={config.color}>{event.eventType}</span>

              <span className="text-fin-muted">Payload Size:</span>
              <span className="text-fin-text">{event.size} bytes ({formatSize(event.size)})</span>

              {event.sessionId && (
                <>
                  <span className="text-fin-muted">Session ID:</span>
                  <span className="text-fin-text">{event.sessionId}</span>
                </>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
