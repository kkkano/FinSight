import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, Terminal } from 'lucide-react';
import { useStore } from '../../store/useStore';
import { AgentEventRow, EventDetail } from './AgentEventRow';
import { AgentLogToolbar } from './AgentLogToolbar';
import { exportEvents } from './AgentLogExport';
import { eventStats, filterEvents, formatSize, projectEvents } from './eventModel';
import type { ConsoleEvent } from './eventModel';

export function AgentLogPanel() {
  const { rawEvents, clearRawEvents, isConsoleOpen, setConsoleOpen, traceRawShowRawJson, setTraceRawShowRawJson } = useStore();
  const events = useMemo(() => projectEvents(rawEvents), [rawEvents]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [searchText, setSearchText] = useState('');
  const [typeFilter, setTypeFilter] = useState<Set<string>>(new Set());
  const [agentFilter, setAgentFilter] = useState<Set<string> | null>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const [isMaximized, setIsMaximized] = useState(false);
  const [pausedEvents, setPausedEvents] = useState<ConsoleEvent[] | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const displayed = pausedEvents ?? events;
  const filtered = useMemo(() => filterEvents(displayed, searchText, typeFilter, agentFilter), [displayed, searchText, typeFilter, agentFilter]);
  const stats = useMemo(() => eventStats(displayed, filtered.length), [displayed, filtered]);
  const agents = useMemo(() => Array.from(new Map(displayed.map((event) => [event.agentKey,
    { id: event.agentKey, label: `${event.agentLabel} · ${event.frame.agent_id ?? 'root'}` }])).values()), [displayed]);
  const selected = filtered.find((event) => event.id === selectedId);
  const showDetail = selected && traceRawShowRawJson;

  useEffect(() => {
    if (autoScroll && pausedEvents === null && listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [filtered, autoScroll, pausedEvents]);

  useEffect(() => {
    const keydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setIsMaximized(false);
      if ((event.ctrlKey || event.metaKey) && event.key === 'f' && isConsoleOpen) {
        event.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener('keydown', keydown);
    return () => window.removeEventListener('keydown', keydown);
  }, [isConsoleOpen]);

  const togglePause = useCallback(() => setPausedEvents((previous) => previous === null ? [...events] : null), [events]);
  const toggleType = (type: string) => setTypeFilter((previous) => {
    const next = new Set(previous);
    if (next.has(type)) next.delete(type); else next.add(type);
    return next;
  });
  const toggleAgent = (id: string) => setAgentFilter((previous) => {
    const next = new Set(previous ?? agents.map((agent) => agent.id));
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  const clear = () => {
    clearRawEvents();
    setPausedEvents(null);
    setSelectedId(null);
    setTypeFilter(new Set());
    setAgentFilter(null);
  };

  if (!isConsoleOpen) return <button type="button" onClick={() => setConsoleOpen(true)}
    className="flex w-full items-center justify-between rounded-xl border border-t-border bg-t-card p-2.5 text-2xs hover:bg-t-hover">
    <span className="flex items-center gap-2 text-t-text2"><Terminal size={13} />Console</span>
    <span className="flex items-center gap-2 text-t-text3">{events.length} events<ChevronDown size={12} /></span>
  </button>;

  const content = <section aria-label="开发者事件日志"
    className={`flex min-h-0 flex-col overflow-hidden bg-t-card font-mono ${isMaximized ? 'h-full' : 'rounded-xl border border-t-border'}`}
    style={isMaximized ? undefined : { maxHeight: '50vh' }}>
    <AgentLogToolbar onClose={() => setConsoleOpen(false)} isPaused={pausedEvents !== null} onTogglePause={togglePause}
      searchText={searchText} onSearchChange={setSearchText} searchRef={searchRef} autoScroll={autoScroll} onToggleAutoScroll={() => setAutoScroll(!autoScroll)}
      showJson={traceRawShowRawJson} onToggleJson={() => setTraceRawShowRawJson(!traceRawShowRawJson)} onExport={() => exportEvents(filtered)}
      isMaximized={isMaximized} onToggleMaximize={() => setIsMaximized(!isMaximized)} onClear={clear}
      typeFilter={typeFilter} onTypeFilter={toggleType} onClearTypeFilter={() => setTypeFilter(new Set())}
      agentFilter={agentFilter} onAgentFilter={toggleAgent} onSelectAllAgents={() => setAgentFilter(null)}
      onDeselectAllAgents={() => setAgentFilter(new Set())} agents={agents} stats={stats} />
    <div className={`flex min-h-0 flex-1 ${isMaximized ? '' : 'max-h-[35vh]'}`}>
      <div ref={listRef} className={`min-w-0 overflow-y-auto ${showDetail ? 'w-1/2 border-r border-t-border' : 'w-full'}`}>
        {filtered.length ? filtered.map((event) => <AgentEventRow key={event.id} event={event} isSelected={event.id === selectedId}
          onClick={() => setSelectedId(event.id === selectedId ? null : event.id)} />)
          : <p className="p-6 text-center text-2xs text-t-text3">{events.length ? '没有匹配的事件' : '等待 schema v2 事件'}</p>}
      </div>
      {showDetail && <div className="min-w-0 w-1/2"><EventDetail key={selected.id} event={selected} onClose={() => setSelectedId(null)} /></div>}
    </div>
    <footer className="flex items-center justify-between gap-2 border-t border-t-border bg-t-bg px-2 py-1 text-2xs text-t-text3">
      <span data-testid="agent-log-event-count">{stats.filtered}/{stats.total} events</span>
      <span>{stats.runningAgents} active · {formatSize(stats.totalBytes)}</span>
    </footer>
  </section>;
  return isMaximized ? <div className="fixed inset-0 z-[200] flex flex-col bg-t-bg">{content}</div> : content;
}
