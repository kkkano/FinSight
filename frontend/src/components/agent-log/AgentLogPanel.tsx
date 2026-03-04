import { useState, useRef, useEffect, useMemo, useCallback } from 'react';
import { Terminal, ChevronDown } from 'lucide-react';
import { useStore } from '../../store/useStore';
import type { RawSSEEvent, RawEventType } from '../../types';
import { getEventSummary, type EventStats } from './constants';
import { AgentLogToolbar } from './AgentLogToolbar';
import { AgentEventRow, EventDetail } from './AgentEventRow';
import { AgentStatusBar } from './AgentStatusBar';
import { exportEvents } from './AgentLogExport';

type ConsoleLens = 'event_stream' | 'agent_pipeline';

const STREAM_EVENT_TYPES = new Set<RawEventType>([
  'thinking',
  'tool_start',
  'tool_end',
  'tool_call',
  'llm_start',
  'llm_end',
  'llm_call',
  'step_start',
  'step_done',
  'step_error',
]);

const AGENT_LABELS: Record<string, string> = {
  supervisor: 'Supervisor',
  planner: 'Planner',
  forum: 'Forum',
  price_agent: 'Price',
  news_agent: 'News',
  fundamental_agent: 'Fundamental',
  technical_agent: 'Technical',
  macro_agent: 'Macro',
  risk_agent: 'Risk',
  deep_search_agent: 'DeepSearch',
  system: 'System',
};

// Known agent names — anything not in this set gets mapped to 'system'
const KNOWN_AGENTS = new Set(Object.keys(AGENT_LABELS));

const canonicalAgentName = (value: unknown): string | null => {
  const raw = String(value || '').trim().toLowerCase();
  if (!raw) return null;
  if (raw === 'supervisoragent' || raw === 'supervisor') return 'supervisor';
  if (raw === 'deepsearchagent' || raw === 'deep_search' || raw === 'deepsearch') return 'deep_search_agent';
  if (raw === 'priceagent' || raw === 'price') return 'price_agent';
  if (raw === 'newsagent' || raw === 'news') return 'news_agent';
  if (raw === 'fundamentalagent' || raw === 'fundamental') return 'fundamental_agent';
  if (raw === 'technicalagent' || raw === 'technical') return 'technical_agent';
  if (raw === 'macroagent' || raw === 'macro') return 'macro_agent';
  if (raw === 'riskagent' || raw === 'risk') return 'risk_agent';
  if (raw.includes('deep_search_agent')) return 'deep_search_agent';
  if (raw.includes('fundamental_agent')) return 'fundamental_agent';
  if (raw.includes('technical_agent')) return 'technical_agent';
  if (raw.includes('price_agent')) return 'price_agent';
  if (raw.includes('news_agent')) return 'news_agent';
  if (raw.includes('macro_agent')) return 'macro_agent';
  if (raw.includes('risk_agent')) return 'risk_agent';
  if (raw.includes('supervisor')) return 'supervisor';
  if (raw.includes('planner')) return 'planner';
  if (raw.includes('forum')) return 'forum';
  if (raw.includes('system')) return 'system';
  // Unknown values → null (mapped to 'system' by getEventAgent)
  return null;
};

const getEventAgent = (event: RawSSEEvent): string => {
  const data = event.parsedData || {};
  const inferred =
    canonicalAgentName(data.agent) ||
    canonicalAgentName(data.agent_name) ||
    canonicalAgentName(data.name) ||
    canonicalAgentName(data.source) ||
    canonicalAgentName(data.stage);
  if (inferred && KNOWN_AGENTS.has(inferred)) return inferred;

  if (event.eventType.startsWith('forum_')) return 'forum';
  if (event.eventType.startsWith('supervisor_')) return 'supervisor';
  if (event.eventType.startsWith('agent_')) return canonicalAgentName(data.agent) || 'system';
  // LangGraph internal events → system
  if (event.eventType.startsWith('langgraph_')) return 'system';
  if (event.eventType === 'system') return 'system';
  return 'system';
};

const AGENT_ORDER = [
  'supervisor',
  'planner',
  'forum',
  'price_agent',
  'news_agent',
  'fundamental_agent',
  'technical_agent',
  'macro_agent',
  'risk_agent',
  'deep_search_agent',
  'system',
];

const sortAgents = (agents: string[]): string[] => {
  const orderMap = new Map(AGENT_ORDER.map((name, idx) => [name, idx]));
  return [...agents].sort((a, b) => {
    const ai = orderMap.has(a) ? (orderMap.get(a) as number) : 999;
    const bi = orderMap.has(b) ? (orderMap.get(b) as number) : 999;
    if (ai !== bi) return ai - bi;
    return a.localeCompare(b);
  });
};

export const AgentLogPanel: React.FC = () => {
  const {
    rawEvents,
    clearRawEvents,
    isConsoleOpen,
    setConsoleOpen,
    agentStatuses,
    requestMetrics,
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
  const [consoleLens, setConsoleLens] = useState<ConsoleLens>('event_stream');
  const [selectedAgents, setSelectedAgents] = useState<Set<string>>(new Set());
  // Track whether user explicitly deselected all agents (vs initial empty state)
  const hasExplicitDeselect = useRef(false);

  const listRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  // Count running agents
  const runningAgents = Object.values(agentStatuses).filter(s => s.status === 'running').length;

  // Freeze event list when paused
  const displayEvents = isPaused ? pausedEvents : rawEvents;

  const availableAgents = useMemo(() => {
    const pool = new Set<string>();
    displayEvents.forEach((event) => {
      pool.add(getEventAgent(event));
    });
    return sortAgents(Array.from(pool));
  }, [displayEvents]);

  useEffect(() => {
    setSelectedAgents((prev) => {
      if (availableAgents.length === 0) return new Set();
      // User explicitly deselected all → keep empty
      if (hasExplicitDeselect.current) return new Set();
      if (prev.size === 0) return new Set(availableAgents);
      const next = new Set(Array.from(prev).filter((agent) => availableAgents.includes(agent)));
      return next.size > 0 ? next : new Set(availableAgents);
    });
  }, [availableAgents]);

  // Apply filters
  const filteredEvents = useMemo(() => {
    let events = displayEvents;

    if (consoleLens === 'event_stream') {
      events = events.filter((e) => STREAM_EVENT_TYPES.has(e.eventType));
    }

    if (consoleLens === 'agent_pipeline') {
      // Empty selectedAgents = show nothing (user explicitly deselected all)
      if (selectedAgents.size === 0) {
        events = [];
      } else {
        events = events.filter((e) => selectedAgents.has(getEventAgent(e)));
      }
    }

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
  }, [displayEvents, consoleLens, selectedAgents, availableAgents, typeFilter, searchText, showTokens]);

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

  const toggleAgentFilter = useCallback((agent: string) => {
    setSelectedAgents((prev) => {
      const next = new Set(prev);
      if (next.has(agent)) {
        next.delete(agent);
      } else {
        next.add(agent);
        // User actively selected an agent → clear explicit deselect
        hasExplicitDeselect.current = false;
      }
      // If all deselected via individual toggles, mark as explicit
      if (next.size === 0) {
        hasExplicitDeselect.current = true;
      }
      return next;
    });
  }, []);

  const selectAllAgents = useCallback(() => {
    hasExplicitDeselect.current = false;
    setSelectedAgents(new Set(availableAgents));
  }, [availableAgents]);

  const deselectAllAgents = useCallback(() => {
    hasExplicitDeselect.current = true;
    setSelectedAgents(new Set());
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

      {/* Lens controls (A/B) */}
      <div className="flex items-center gap-2 px-2 py-1 bg-fin-bg border-b border-fin-border/50 overflow-x-auto scrollbar-hide">
        <button
          type="button"
          onClick={() => setConsoleLens('event_stream')}
          className={`px-2 py-0.5 rounded text-[10px] font-semibold whitespace-nowrap ${
            consoleLens === 'event_stream'
              ? 'bg-cyan-500/15 text-cyan-300 border border-cyan-500/30'
              : 'bg-fin-panel text-fin-muted border border-fin-border hover:text-fin-text'
          }`}
          title="A：只看 think/tool/tool call/llm 关键事件"
        >
          A 事件流 (think/tool/llm)
        </button>
        <button
          type="button"
          onClick={() => {
            setConsoleLens('agent_pipeline');
            setTraceRawShowRawJson(true);
          }}
          className={`px-2 py-0.5 rounded text-[10px] font-semibold whitespace-nowrap ${
            consoleLens === 'agent_pipeline'
              ? 'bg-violet-500/15 text-violet-300 border border-violet-500/30'
              : 'bg-fin-panel text-fin-muted border border-fin-border hover:text-fin-text'
          }`}
          title="B：看全部 Agent 链路（输入/输出/流程/决策）"
        >
          B Agent 全链路
        </button>

        <span className="text-[9px] text-fin-muted whitespace-nowrap">
          {consoleLens === 'event_stream'
            ? '聚焦关键执行事件'
            : '可多选 Agent 联合观察，点击事件看完整 JSON'}
        </span>
      </div>

      {/* B mode agent selector */}
      {consoleLens === 'agent_pipeline' && (
        <div className="flex items-center gap-1 px-2 py-1 bg-fin-panel border-b border-fin-border/50 overflow-x-auto scrollbar-hide">
          <button
            type="button"
            onClick={selectAllAgents}
            className="px-1.5 py-[1px] rounded text-[9px] border border-fin-border text-fin-muted hover:text-fin-text whitespace-nowrap"
          >
            全选
          </button>
          <button
            type="button"
            onClick={deselectAllAgents}
            className="px-1.5 py-[1px] rounded text-[9px] border border-fin-border text-fin-muted hover:text-fin-text whitespace-nowrap"
          >
            全取消
          </button>
          {availableAgents.map((agent, idx) => {
            const active = selectedAgents.has(agent);
            return (
              <button
                key={agent}
                type="button"
                onClick={() => toggleAgentFilter(agent)}
                className={`px-1.5 py-[1px] rounded text-[9px] border whitespace-nowrap transition-colors ${
                  active
                    ? 'border-fin-primary/40 bg-fin-primary/10 text-fin-primary'
                    : 'border-fin-border text-fin-muted hover:text-fin-text'
                }`}
                title={agent}
              >
                {idx + 1}. {AGENT_LABELS[agent] || agent}
              </button>
            );
          })}
        </div>
      )}

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
        requestMetrics={requestMetrics}
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
