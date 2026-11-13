import type { RefObject } from 'react';
import { Terminal, ChevronUp, Search, Pause, Play, Download, Maximize2, Minimize2, Trash2, Eye, EyeOff } from 'lucide-react';
import type { EventStats } from './eventModel';

interface AgentLogToolbarProps {
  onClose: () => void;
  isPaused: boolean;
  onTogglePause: () => void;
  searchText: string;
  onSearchChange: (value: string) => void;
  searchRef: RefObject<HTMLInputElement | null>;
  autoScroll: boolean;
  onToggleAutoScroll: () => void;
  showJson: boolean;
  onToggleJson: () => void;
  onExport: () => void;
  isMaximized: boolean;
  onToggleMaximize: () => void;
  onClear: () => void;
  typeFilter: ReadonlySet<string>;
  onTypeFilter: (value: string) => void;
  onClearTypeFilter: () => void;
  agentFilter: ReadonlySet<string> | null;
  onAgentFilter: (value: string) => void;
  onSelectAllAgents: () => void;
  onDeselectAllAgents: () => void;
  agents: Array<{ id: string; label: string }>;
  stats: EventStats;
}

export function AgentLogToolbar({ searchRef, ...props }: AgentLogToolbarProps) {
  const button = 'p-1 rounded text-t-text3 hover:text-t-text hover:bg-t-hover';
  return <>
    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-t-border bg-t-bg px-2 py-1.5">
      <button type="button" onClick={props.onClose} className="flex items-center gap-1.5 text-2xs text-t-text2" aria-label="折叠开发者日志">
        <Terminal size={13} /><span>Console</span><ChevronUp size={12} />
      </button>
      <span className="text-2xs text-t-text3">schema v2{props.isPaused ? ' · 已暂停' : ''}</span>
      <div className="flex items-center gap-1">
        <button type="button" className={button} onClick={props.onTogglePause} title={props.isPaused ? '继续日志' : '暂停日志'}>
          {props.isPaused ? <Play size={13} /> : <Pause size={13} />}
        </button>
        <button type="button" className={button} onClick={props.onToggleAutoScroll} aria-pressed={props.autoScroll} title="自动滚动">↓</button>
        <button type="button" className={button} onClick={props.onToggleJson} aria-pressed={props.showJson} title="显示事件JSON">
          {props.showJson ? <Eye size={13} /> : <EyeOff size={13} />}
        </button>
        <button type="button" className={button} onClick={props.onExport} title="导出日志"><Download size={13} /></button>
        <button type="button" className={button} onClick={props.onToggleMaximize} title={props.isMaximized ? '退出全屏' : '全屏日志'}>
          {props.isMaximized ? <Minimize2 size={13} /> : <Maximize2 size={13} />}
        </button>
        <button type="button" className={button} onClick={props.onClear} title="清空日志"><Trash2 size={13} /></button>
      </div>
    </div>
    <div className="flex flex-wrap items-center gap-2 border-b border-t-border bg-t-card px-2 py-1.5 text-2xs">
      <label className="flex min-w-0 flex-1 items-center gap-1 text-t-text3"><Search size={12} />
        <input ref={searchRef} aria-label="筛选日志" placeholder="筛选日志" value={props.searchText}
          onChange={(event) => props.onSearchChange(event.target.value)} className="min-w-0 w-full bg-transparent text-t-text outline-none" />
      </label>
    </div>
    <div role="group" aria-label="事件类型" className="flex items-center gap-1 overflow-x-auto border-b border-t-border px-2 py-1 text-2xs">
      <button type="button" className={button} onClick={props.onClearTypeFilter}>全部事件</button>
      {Object.entries(props.stats.typeCounts).map(([type, count]) => <button key={type} type="button"
        onClick={() => props.onTypeFilter(type)} aria-pressed={!props.typeFilter.size || props.typeFilter.has(type)}
        className={`shrink-0 rounded px-1.5 py-0.5 ${!props.typeFilter.size || props.typeFilter.has(type) ? 'bg-t-accent/10 text-t-accent' : 'text-t-text3'}`}>
        {type} · {count}
      </button>)}
    </div>
    <div role="group" aria-label="Agent" className="flex items-center gap-1 overflow-x-auto border-b border-t-border px-2 py-1 text-2xs">
      <button type="button" className={button} onClick={props.onSelectAllAgents}>全选</button>
      <button type="button" className={button} onClick={props.onDeselectAllAgents}>全取消</button>
      {props.agents.map((agent) => <button key={agent.id} type="button" onClick={() => props.onAgentFilter(agent.id)}
        aria-pressed={props.agentFilter === null || props.agentFilter.has(agent.id)} title={agent.id}
        className={`shrink-0 rounded px-1.5 py-0.5 ${props.agentFilter === null || props.agentFilter.has(agent.id) ? 'bg-t-accent/10 text-t-accent' : 'text-t-text3'}`}>
        {agent.label}
      </button>)}
    </div>
  </>;
}
