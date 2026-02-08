import { useState, useRef, useEffect, useMemo, useCallback } from 'react';
import { Terminal, ChevronDown, Zap } from 'lucide-react';
import { useStore } from '../../store/useStore';
import type { RawSSEEvent, RawEventType } from '../../types';
import { getEventSummary, type EventStats } from './constants';
import { AgentLogToolbar } from './AgentLogToolbar';
import { AgentEventRow, EventDetail } from './AgentEventRow';
import { AgentStatusBar } from './AgentStatusBar';
import { exportEvents } from './AgentLogExport';

export const AgentLogPanel: React.FC = () => {
  const {
    rawEvents,
    clearRawEvents,
    isConsoleOpen,
    setConsoleOpen,
    agentStatuses,
    traceViewMode,
    traceRawShowRawJson,
    setTraceRawShowRawJson,
  } = useStore();

  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [searchText, setSearchText] = useState('');
  const [autoScroll, setAutoScroll] = useState(true);
  const [showTokens, setShowTokens] = useState(false);
  const [isMaximized, setIsMaximized] = useState(false);
  const [typeFilter, setTypeFilter] = useState<Set<RawEventType>>(new Set());
  const [isPaused, setIsPaused] = useState(false);
  const [pausedEvents, setPausedEvents] = useState<RawSSEEvent[]>([]);

  const listRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  // Count running agents
  const runningAgents = Object.values(agentStatuses).filter(s => s.status === 'running').length;

  // Freeze event list when paused
  const displayEvents = isPaused ? pausedEvents : rawEvents;

  // Apply filters
  const filteredEvents = useMemo(() => {
    let events = displayEvents;

    if (typeFilter.size > 0) {
      events = events.filter(e => typeFilter.has(e.eventType));
    }

    if (searchText.trim()) {
      const lower = searchText.toLowerCase();
      events = events.filter(e =>
        e.rawData.toLowerCase().includes(lower) ||
        e.eventType.toLowerCase().includes(lower) ||
        getEventSummary(e).toLowerCase().includes(lower)
      );
    }

    if (!showTokens) {
      events = events.filter(e => e.eventType !== 'token');
    }

    return events;
  }, [displayEvents, typeFilter, searchText, showTokens]);

  // Compute stats
  const stats: EventStats = useMemo(() => {
    const totalBytes = rawEvents.reduce((sum, e) => sum + e.size, 0);
    const typeCounts: Record<string, number> = {};
    rawEvents.forEach(e => {
      typeCounts[e.eventType] = (typeCounts[e.eventType] || 0) + 1;
    });
    return { total: rawEvents.length, totalBytes, typeCounts, filtered: filteredEvents.length };
  }, [rawEvents, filteredEvents]);

  // Selected event
  const selectedEvent = useMemo(
    () => filteredEvents.find(e => e.id === selectedEventId) || null,
    [filteredEvents, selectedEventId]
  );

  // Auto-scroll to bottom
  useEffect(() => {
    if (autoScroll && !isPaused && listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [filteredEvents, autoScroll, isPaused]);

  // Pause / Resume
  const togglePause = useCallback(() => {
    if (!isPaused) {
      setPausedEvents([...rawEvents]);
    }
    setIsPaused(!isPaused);
  }, [isPaused, rawEvents]);

  // Export handler
  const handleExport = useCallback(() => {
    exportEvents(filteredEvents);
  }, [filteredEvents]);

  // Toggle a single type filter
  const toggleTypeFilter = useCallback((type: RawEventType) => {
    setTypeFilter(prev => {
      const next = new Set(prev);
      if (next.has(type)) {
        next.delete(type);
      } else {
        next.add(type);
      }
      return next;
    });
  }, []);

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isMaximized) {
        setIsMaximized(false);
      }
      if ((e.ctrlKey || e.metaKey) && e.key === 'f' && isConsoleOpen) {
        e.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isMaximized, isConsoleOpen]);

  // --- Collapsed state ---
  if (!isConsoleOpen) {
    return (
      <button
        onClick={() => setConsoleOpen(true)}
        className="w-full p-2.5 bg-fin-card border border-fin-border rounded-xl hover:bg-fin-hover transition-colors flex items-center justify-between group"
      >
        <div className="flex items-center gap-2">
          <Terminal size={13} className="text-fin-primary" />
          <span className="text-[11px] font-mono font-bold text-fin-text-secondary uppercase tracking-wider">Console</span>
        </div>
        <div className="flex items-center gap-2">
          {runningAgents > 0 && (
            <span className="text-2xs px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400 animate-pulse font-mono">
              {runningAgents} active
            </span>
          )}
          <span className="text-2xs text-fin-muted font-mono">{rawEvents.length} events</span>
          <ChevronDown size={12} className="text-fin-muted group-hover:text-fin-text" />
        </div>
      </button>
    );
  }

  // --- Expanded content ---
  const consoleContent = (
    <div
      className={`flex flex-col bg-fin-card overflow-hidden font-mono shadow-sm ${isMaximized ? 'h-full' : 'border border-fin-border rounded-xl'}`}
      style={isMaximized ? {} : { maxHeight: '50vh' }}
    >
      {/* Toolbar */}
      <AgentLogToolbar
        onClose={() => setConsoleOpen(false)}
        isPaused={isPaused}
        onTogglePause={togglePause}
        runningAgents={runningAgents}
        traceViewMode={traceViewMode}
        searchText={searchText}
        onSearchChange={setSearchText}
        searchRef={searchRef}
        showTokens={showTokens}
        onToggleTokens={() => setShowTokens(prev => !prev)}
        traceRawShowRawJson={traceRawShowRawJson}
        onToggleRawJson={() => setTraceRawShowRawJson(!traceRawShowRawJson)}
        autoScroll={autoScroll}
        onToggleAutoScroll={() => setAutoScroll(prev => !prev)}
        onExport={handleExport}
        isMaximized={isMaximized}
        onToggleMaximize={() => setIsMaximized(prev => !prev)}
        onClear={() => { clearRawEvents(); setSelectedEventId(null); }}
        typeFilter={typeFilter}
        onToggleTypeFilter={toggleTypeFilter}
        onClearTypeFilter={() => setTypeFilter(new Set())}
        stats={stats}
      />

      {/* Event list + detail panel */}
      <div className={`flex flex-1 min-h-0 ${isMaximized ? '' : 'max-h-[35vh]'}`}>
        {/* Left: event list */}
        <div
          ref={listRef}
          className={`overflow-y-auto overflow-x-hidden scrollbar-thin ${
            selectedEvent ? 'w-1/2 border-r border-fin-border' : 'w-full'
          }`}
        >
          {filteredEvents.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-fin-muted">
              <Terminal size={24} className="mb-2 opacity-30" />
              <p className="text-[11px]">
                {rawEvents.length === 0
                  ? 'Waiting for events...'
                  : 'No matching events'
                }
              </p>
              <p className="text-2xs text-fin-muted/70">
                {rawEvents.length === 0
                  ? 'Send a message to see raw SSE event stream'
                  : `${rawEvents.length} events hidden by filters`
                }
              </p>
            </div>
          ) : (
            filteredEvents.map((event, idx) => (
              <AgentEventRow
                key={event.id}
                event={event}
                index={idx + 1}
                isSelected={event.id === selectedEventId}
                onClick={() => setSelectedEventId(event.id === selectedEventId ? null : event.id)}
                showTokens={showTokens}
                traceViewMode={traceViewMode}
              />
            ))
          )}
        </div>

        {/* Right: detail panel */}
        {selectedEvent && traceRawShowRawJson && (
          <div className="w-1/2 overflow-hidden">
            <EventDetail event={selectedEvent} onClose={() => setSelectedEventId(null)} />
          </div>
        )}
      </div>

      {/* Status bar */}
      <AgentStatusBar
        stats={stats}
        showTokens={showTokens}
        agentStatuses={agentStatuses}
      />
    </div>
  );

  // Fullscreen overlay
  if (isMaximized) {
    return (
      <div className="fixed inset-0 z-[200] bg-fin-bg/95 backdrop-blur-sm flex flex-col">
        {consoleContent}
      </div>
    );
  }

  return consoleContent;
};
