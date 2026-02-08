import type React from 'react';
import {
  Terminal,
  ChevronUp,
  Search,
  X,
  Eye,
  EyeOff,
  Pause,
  Play,
  Download,
  Maximize2,
  Minimize2,
  Trash2,
  Zap,
} from 'lucide-react';
import type { RawEventType, TraceViewMode } from '../../types';
import { EVENT_TYPE_CONFIG, type EventStats } from './constants';

export interface AgentLogToolbarProps {
  // Console toggle
  onClose: () => void;
  // Pause state
  isPaused: boolean;
  onTogglePause: () => void;
  // Running agents
  runningAgents: number;
  // Trace view mode
  traceViewMode: TraceViewMode;
  // Search
  searchText: string;
  onSearchChange: (text: string) => void;
  searchRef: React.RefObject<HTMLInputElement | null>;
  // Token visibility
  showTokens: boolean;
  onToggleTokens: () => void;
  // Raw JSON toggle
  traceRawShowRawJson: boolean;
  onToggleRawJson: () => void;
  // Auto-scroll
  autoScroll: boolean;
  onToggleAutoScroll: () => void;
  // Export
  onExport: () => void;
  // Maximize
  isMaximized: boolean;
  onToggleMaximize: () => void;
  // Clear
  onClear: () => void;
  // Type filter
  typeFilter: Set<RawEventType>;
  onToggleTypeFilter: (type: RawEventType) => void;
  onClearTypeFilter: () => void;
  // Stats for type filter counts
  stats: EventStats;
}

export const AgentLogToolbar: React.FC<AgentLogToolbarProps> = ({
  onClose,
  isPaused,
  onTogglePause,
  runningAgents,
  traceViewMode,
  searchText,
  onSearchChange,
  searchRef,
  showTokens,
  onToggleTokens,
  traceRawShowRawJson,
  onToggleRawJson,
  autoScroll,
  onToggleAutoScroll,
  onExport,
  isMaximized,
  onToggleMaximize,
  onClear,
  typeFilter,
  onToggleTypeFilter,
  onClearTypeFilter,
  stats,
}) => {
  return (
    <>
      {/* Top toolbar row */}
      <div className="flex items-center justify-between px-2 py-1.5 bg-fin-bg border-b border-fin-border">
        {/* Left side */}
        <div className="flex items-center gap-2">
          <button
            onClick={onClose}
            className="flex items-center gap-1.5 hover:opacity-80"
          >
            <Terminal size={13} className="text-fin-primary" />
            <span className="text-[11px] font-bold text-fin-text-secondary uppercase tracking-wider">Console</span>
            <ChevronUp size={12} className="text-fin-muted" />
          </button>

          {isPaused && (
            <span className="text-2xs px-1.5 py-0.5 rounded bg-fin-danger/15 text-fin-danger font-bold animate-pulse">
              PAUSED
            </span>
          )}

          {runningAgents > 0 && !isPaused && (
            <span className="text-2xs px-1.5 py-0.5 rounded bg-fin-success/15 text-fin-success flex items-center gap-1">
              <Zap size={9} className="animate-pulse" />
              {runningAgents} active
            </span>
          )}

          <span className="text-2xs px-1.5 py-0.5 rounded bg-fin-panel border border-fin-border/60 text-fin-muted">
            {traceViewMode === 'user' ? '\u7528\u6237\u89c6\u56fe' : traceViewMode === 'expert' ? '\u4e13\u5bb6\u89c6\u56fe' : '\u5f00\u53d1\u89c6\u56fe'}
          </span>
        </div>

        {/* Right side tool buttons */}
        <div className="flex items-center gap-1">
          {/* Search input */}
          <div className="relative flex items-center">
            <Search size={10} className="absolute left-1.5 text-fin-muted" />
            <input
              ref={searchRef}
              type="text"
              value={searchText}
              onChange={(e) => onSearchChange(e.target.value)}
              placeholder="Filter..."
              className="w-24 focus:w-36 transition-all bg-fin-panel border border-fin-border rounded text-2xs text-fin-text pl-5 pr-1.5 py-0.5 focus:outline-none focus:border-fin-primary/50 placeholder-fin-muted"
            />
            {searchText && (
              <button
                onClick={() => onSearchChange('')}
                className="absolute right-1 text-fin-muted hover:text-fin-text"
              >
                <X size={9} />
              </button>
            )}
          </div>

          {/* Token toggle */}
          <button
            onClick={onToggleTokens}
            className={`p-1 rounded text-2xs transition-colors ${showTokens ? 'text-fin-text bg-fin-hover' : 'text-fin-muted hover:text-fin-text'}`}
            title={showTokens ? 'Hide token events' : 'Show token events'}
          >
            {showTokens ? <Eye size={11} /> : <EyeOff size={11} />}
          </button>

          {/* Raw JSON toggle */}
          <button
            onClick={onToggleRawJson}
            className={`p-1 rounded text-2xs transition-colors ${traceRawShowRawJson ? 'text-fin-text bg-fin-hover' : 'text-fin-muted hover:text-fin-text'}`}
            title={traceRawShowRawJson ? 'Hide raw JSON payload' : 'Show raw JSON payload'}
          >
            {traceRawShowRawJson ? <Eye size={11} /> : <EyeOff size={11} />}
          </button>

          {/* Pause / Resume */}
          <button
            onClick={onTogglePause}
            className={`p-1 rounded transition-colors ${isPaused ? 'text-fin-danger bg-fin-danger/10' : 'text-fin-muted hover:text-fin-text'}`}
            title={isPaused ? 'Resume' : 'Pause'}
          >
            {isPaused ? <Play size={11} /> : <Pause size={11} />}
          </button>

          {/* Auto-scroll */}
          <button
            onClick={onToggleAutoScroll}
            className={`p-1 rounded text-2xs font-bold transition-colors ${autoScroll ? 'text-fin-primary bg-fin-primary/10' : 'text-fin-muted hover:text-fin-text'}`}
            title={autoScroll ? 'Auto-scroll ON' : 'Auto-scroll OFF'}
          >
            \u2193
          </button>

          {/* Export */}
          <button
            onClick={onExport}
            className="p-1 rounded text-fin-muted hover:text-fin-text transition-colors"
            title="Export logs"
          >
            <Download size={11} />
          </button>

          {/* Fullscreen */}
          <button
            onClick={onToggleMaximize}
            className="p-1 rounded text-fin-muted hover:text-fin-text transition-colors"
            title={isMaximized ? 'Exit fullscreen' : 'Fullscreen'}
          >
            {isMaximized ? <Minimize2 size={11} /> : <Maximize2 size={11} />}
          </button>

          {/* Clear */}
          <button
            onClick={onClear}
            className="p-1 rounded text-fin-muted hover:text-fin-danger transition-colors"
            title="Clear console"
          >
            <Trash2 size={11} />
          </button>
        </div>
      </div>

      {/* Type filter row */}
      <div className="flex items-center gap-1 px-2 py-1 bg-fin-panel border-b border-fin-border/50 overflow-x-auto scrollbar-none">
        <span className="text-[9px] text-fin-muted shrink-0">TYPE:</span>
        {Object.entries(EVENT_TYPE_CONFIG)
          .filter(([key]) => key !== 'any')
          .map(([key, cfg]) => {
            const count = stats.typeCounts[key] || 0;
            const isActive = typeFilter.size === 0 || typeFilter.has(key as RawEventType);
            return (
              <button
                key={key}
                onClick={() => onToggleTypeFilter(key as RawEventType)}
                className={`flex items-center gap-0.5 px-1.5 py-[1px] rounded text-[9px] whitespace-nowrap transition-all ${
                  isActive
                    ? `${cfg.bg} ${cfg.color}`
                    : 'text-fin-muted/50 hover:text-fin-muted'
                }`}
              >
                {cfg.icon} {cfg.label}
                {count > 0 && <span className="text-[8px] opacity-60 ml-0.5">{count}</span>}
              </button>
            );
          })}
        {typeFilter.size > 0 && (
          <button
            onClick={onClearTypeFilter}
            className="text-[9px] text-fin-muted hover:text-fin-text px-1"
          >
            \u2715 clear
          </button>
        )}
      </div>
    </>
  );
};
