import { useEffect, useMemo, useState } from 'react';
import { Bot, Check, Loader2, Minus, X } from 'lucide-react';

import type { AgentProfileMap, AgentProfileView } from '../../types/agents';
import type { AgentRunInfo, ExecutionRun, TimelineEvent } from '../../types/execution';
import { normalizeAgentName } from '../../utils/userMessageMapper';

type AgentWorkLogProps = {
  run: ExecutionRun;
  className?: string;
  profiles?: AgentProfileMap;
};

type WorkLogRow = {
  key: string;
  displayName: string;
  info: AgentRunInfo;
  action: string;
  timestamp: number;
  profile?: AgentProfileView;
};

const TERMINAL_AGENT_STATUSES = new Set<AgentRunInfo['status']>(['done', 'error', 'skipped']);
const EMPTY_PROFILES: AgentProfileMap = {};

function shortAgentName(name: string): string {
  return name.replace(/_agent$/, '').replaceAll('_', ' ');
}

function eventAgentName(event: TimelineEvent): string | undefined {
  return event.agent || event.name;
}

function latestAgentAction(timeline: TimelineEvent[], agentName: string): string | undefined {
  const normalized = normalizeAgentName(agentName);
  const event = [...timeline].reverse().find((item) => {
    const candidate = eventAgentName(item);
    return candidate && normalizeAgentName(candidate) === normalized;
  });
  return event?.userMessage || event?.message;
}

function durationMs(info: AgentRunInfo, now: number): number | undefined {
  if (typeof info.durationMs === 'number') return info.durationMs;
  const startedAt = info.startedAt ? Date.parse(info.startedAt) : Number.NaN;
  const completedAt = info.completedAt ? Date.parse(info.completedAt) : Number.NaN;
  if (!Number.isFinite(startedAt)) return undefined;
  return Math.max(0, (Number.isFinite(completedAt) ? completedAt : now) - startedAt);
}

function formatDuration(value?: number): string {
  if (value === undefined) return '—';
  return `${(value / 1000).toFixed(1)}s`;
}

function formatRunDuration(run: ExecutionRun, now: number): string {
  const startedAt = Date.parse(run.startedAt);
  const completedAt = run.completedAt ? Date.parse(run.completedAt) : Number.NaN;
  const elapsedMs = Number.isFinite(startedAt)
    ? Math.max(0, (Number.isFinite(completedAt) ? completedAt : now) - startedAt)
    : 0;
  const totalSeconds = Math.floor(elapsedMs / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return minutes > 0 ? `${minutes}m${seconds}s` : `${seconds}s`;
}

function StatusIcon({ status }: { status: AgentRunInfo['status'] }) {
  if (status === 'running') {
    return <Loader2 aria-label="运行中" size={14} className="shrink-0 animate-spin text-t-accent" />;
  }
  if (status === 'done') {
    return <Check aria-label="已完成" size={14} className="shrink-0 text-t-up" />;
  }
  if (status === 'error') {
    return <X aria-label="失败" size={14} className="shrink-0 text-t-down" />;
  }
  return <Minus aria-label={status === 'skipped' ? '已跳过' : '等待中'} size={14} className="shrink-0 text-t-text3" />;
}

export function AgentWorkLog({ run, className = '', profiles: providedProfiles }: AgentWorkLogProps) {
  const [now, setNow] = useState(() => Date.now());
  const profiles = providedProfiles ?? EMPTY_PROFILES;

  useEffect(() => {
    if (run.status !== 'running') return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [run.status]);

  const rows = useMemo<WorkLogRow[]>(() => {
    const deduped = new Map<string, WorkLogRow>();
    const order = run.selectedAgents?.length ? run.selectedAgents : Object.keys(run.agentStatuses);
    for (const name of order) {
      const info = run.agentStatuses[name];
      if (!info) continue;
      const normalized = normalizeAgentName(name);
      const action = latestAgentAction(run.timeline, name)
        || info.currentStep
        || (info.status === 'pending' ? '等待调度' : '处理中');
      const timestamp = Date.parse(info.lastEventAt || info.startedAt || run.startedAt);
      const row = {
        key: normalized,
        displayName: profiles[normalized]?.short_zh || shortAgentName(normalized),
        info,
        action,
        timestamp: Number.isFinite(timestamp) ? timestamp : 0,
        profile: profiles[normalized],
      };
      const existing = deduped.get(normalized);
      if (!existing || row.timestamp >= existing.timestamp || TERMINAL_AGENT_STATUSES.has(info.status)) {
        deduped.set(normalized, row);
      }
    }
    return [...deduped.values()].sort((a, b) => b.timestamp - a.timestamp);
  }, [profiles, run.agentStatuses, run.selectedAgents, run.startedAt, run.timeline]);

  if (rows.length === 0) return null;

  if (run.status !== 'running') {
    const toolCalls = run.timeline.filter((event) => event.eventType === 'tool_start').length;
    return (
      <div className={`flex h-7 items-center gap-2 px-1 text-xs text-t-text2 ${className}`}>
        <Bot size={16} className="shrink-0 text-t-accent" />
        <span className="truncate">
          {rows.length} 个智能体 · {toolCalls} 次取数 · <span className="num">{formatRunDuration(run, now)}</span>
        </span>
      </div>
    );
  }

  return (
    <div className={`mt-2 border-t border-t-divider pt-1 ${className}`}>
      {rows.slice(0, 6).map((row) => (
        <div key={row.key} className="flex h-7 items-center gap-2 text-xs">
          {row.profile ? (
            <span
              className="inline-flex h-4 min-w-4 shrink-0 items-center justify-center rounded border border-current/30 px-0.5 font-mono text-[9px]"
              style={{ color: `var(--${row.profile.color_token})` }}
              title={row.profile.display_name}
            >
              {row.profile.glyph}
            </span>
          ) : (
            <Bot size={16} className="shrink-0 text-t-text3" />
          )}
          <span className="w-14 shrink-0 truncate font-medium text-t-text2">{row.displayName}</span>
          <span className="flex-1 truncate text-t-text3">{row.action}</span>
          <span className="num shrink-0 text-2xs text-t-text3">{formatDuration(durationMs(row.info, now))}</span>
          <StatusIcon status={row.info.status} />
        </div>
      ))}
    </div>
  );
}

export default AgentWorkLog;
