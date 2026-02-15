/**
 * ExecutionBanner — global top bar showing active/recent execution progress.
 *
 * Subscribes to executionStore and shows:
 *   - Running: agent pipeline + progress + cancel
 *   - Recently completed: success/error summary, auto-hides after 3s
 */
import React, { useEffect, useRef, useState } from 'react';
import {
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Loader2,
  StopCircle,
  XCircle,
} from 'lucide-react';

import { useExecutionStore } from '../../store/executionStore';
import type { AgentRunInfo, ExecutionRun } from '../../types/execution';

// --- Constants ---

const AGENT_DISPLAY_ORDER = [
  'price_agent',
  'news_agent',
  'fundamental_agent',
  'technical_agent',
  'macro_agent',
  'deep_search_agent',
];

const AGENT_SHORT_NAMES: Record<string, string> = {
  price_agent: '价格',
  news_agent: '新闻',
  fundamental_agent: '基本面',
  technical_agent: '技术面',
  macro_agent: '宏观',
  deep_search_agent: '搜索',
};

// --- Sub-components ---

function MiniAgentDot({ status }: { status: AgentRunInfo['status'] }) {
  switch (status) {
    case 'running':
      return <Loader2 size={10} className="animate-spin text-blue-400" />;
    case 'done':
      return <CheckCircle2 size={10} className="text-emerald-400" />;
    case 'error':
      return <XCircle size={10} className="text-red-400" />;
    case 'skipped':
      return <span className="w-2.5 h-2.5 rounded-full bg-gray-500 inline-block" />;
    default:
      return <span className="w-2.5 h-2.5 rounded-full border border-fin-border inline-block" />;
  }
}

function AgentPipeline({ agents }: { agents: Record<string, AgentRunInfo> }) {
  const ordered = AGENT_DISPLAY_ORDER
    .filter((name) => agents[name])
    .map((name) => agents[name]);

  const extra = Object.values(agents).filter(
    (a) => !AGENT_DISPLAY_ORDER.includes(a.name),
  );
  const all = [...ordered, ...extra];

  if (all.length === 0) return null;

  return (
    <div className="flex items-center gap-1.5">
      {all.map((agent) => (
        <div
          key={agent.name}
          className="flex items-center gap-0.5"
          title={`${AGENT_SHORT_NAMES[agent.name] ?? agent.name}: ${agent.status}`}
        >
          <MiniAgentDot status={agent.status} />
          <span className="text-2xs text-fin-muted hidden sm:inline">
            {AGENT_SHORT_NAMES[agent.name] ?? agent.name.replace(/_agent$/, '')}
          </span>
        </div>
      ))}
    </div>
  );
}

// --- Main Component ---

export const ExecutionBanner: React.FC = () => {
  const activeRuns = useExecutionStore((s) => s.activeRuns);
  const recentRuns = useExecutionStore((s) => s.recentRuns);
  const cancelExecution = useExecutionStore((s) => s.cancelExecution);

  const [recentlyCompleted, setRecentlyCompleted] = useState<ExecutionRun | null>(null);
  const [expanded, setExpanded] = useState(false);
  const hideTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Track recently completed runs — show for 3s after all active runs finish
  const prevActiveCountRef = useRef(activeRuns.length);
  useEffect(() => {
    if (prevActiveCountRef.current > 0 && activeRuns.length === 0 && recentRuns.length > 0) {
      const latest = recentRuns[recentRuns.length - 1];
      setRecentlyCompleted(latest);

      if (hideTimerRef.current) clearTimeout(hideTimerRef.current);
      hideTimerRef.current = setTimeout(() => {
        setRecentlyCompleted(null);
      }, 3000);
    }
    prevActiveCountRef.current = activeRuns.length;
  }, [activeRuns.length, recentRuns]);

  useEffect(() => {
    return () => {
      if (hideTimerRef.current) clearTimeout(hideTimerRef.current);
    };
  }, []);

  // Determine which run to display
  const displayRun = activeRuns.length > 0
    ? activeRuns[activeRuns.length - 1]
    : recentlyCompleted;

  if (!displayRun) return null;

  const isRunning = displayRun.status === 'running';
  const isDone = displayRun.status === 'done';
  const isError = displayRun.status === 'error';

  const tickerText = displayRun.tickers.length > 0
    ? displayRun.tickers.join(', ')
    : displayRun.query.slice(0, 30);

  return (
    <div
      className={`shrink-0 border-b transition-colors ${
        isRunning
          ? 'border-blue-800/30 bg-blue-950/20'
          : isDone
            ? 'border-emerald-800/30 bg-emerald-950/20'
            : isError
              ? 'border-red-800/30 bg-red-950/20'
              : 'border-fin-border bg-fin-bg/50'
      }`}
    >
      <div className="flex items-center gap-3 px-4 py-2">
        {/* Status icon */}
        {isRunning ? (
          <Loader2 size={14} className="animate-spin text-blue-400 shrink-0" />
        ) : isDone ? (
          <CheckCircle2 size={14} className="text-emerald-400 shrink-0" />
        ) : isError ? (
          <XCircle size={14} className="text-red-400 shrink-0" />
        ) : (
          <StopCircle size={14} className="text-fin-muted shrink-0" />
        )}

        {/* Ticker / query */}
        <span className="text-xs text-fin-text font-medium truncate max-w-32">
          {tickerText}
        </span>

        {/* Agent pipeline */}
        <AgentPipeline agents={displayRun.agentStatuses} />

        {/* Progress (running) */}
        {isRunning && (
          <div className="flex items-center gap-2 ml-auto shrink-0">
            <div className="w-24 h-1.5 rounded-full bg-fin-border overflow-hidden">
              <div
                className="h-full rounded-full bg-blue-500 transition-all duration-300"
                style={{ width: `${displayRun.progress}%` }}
              />
            </div>
            <span className="text-2xs text-blue-400">{displayRun.progress}%</span>
          </div>
        )}

        {/* Current step */}
        {isRunning && displayRun.currentStep && (
          <span className="text-2xs text-fin-muted truncate max-w-40 hidden md:inline">
            {displayRun.currentStep}
          </span>
        )}

        {/* Terminal status text */}
        {!isRunning && (
          <span className="text-2xs text-fin-muted ml-auto shrink-0">
            {isDone ? '执行完成' : isError ? '执行失败' : '已取消'}
          </span>
        )}

        {/* Actions */}
        <div className="flex items-center gap-1 shrink-0">
          <button
            type="button"
            onClick={() => setExpanded((prev) => !prev)}
            className="p-1 rounded hover:bg-fin-hover text-fin-muted hover:text-fin-text transition-colors"
            title={expanded ? '收起' : '展开'}
          >
            {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          </button>

          {isRunning && (
            <button
              type="button"
              onClick={() => cancelExecution(displayRun.runId)}
              className="p-1 rounded hover:bg-red-900/30 text-fin-muted hover:text-red-400 transition-colors"
              title="取消执行"
            >
              <XCircle size={12} />
            </button>
          )}
        </div>
      </div>

      {/* Expanded detail */}
      {expanded && displayRun.streamedContent && (
        <div className="px-4 pb-2">
          <div className="text-xs text-fin-text whitespace-pre-wrap break-words max-h-32 overflow-y-auto border border-fin-border rounded-lg p-2 bg-fin-bg/50">
            {displayRun.streamedContent.slice(-500)}
          </div>
        </div>
      )}
    </div>
  );
};
