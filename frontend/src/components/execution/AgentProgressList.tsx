import { useMemo } from 'react';
import type { ReactNode } from 'react';
import { AlertTriangle, CheckCircle2, Clock3, Loader2, SkipForward } from 'lucide-react';

import type { AgentRunInfo, PlanStepSummary } from '../../types/execution';
import { getAgentDisplayName, normalizeAgentName } from '../../utils/userMessageMapper';

type AgentProgressListProps = {
  agentStatuses: Record<string, AgentRunInfo>;
  selectedAgents?: string[];
  planSteps?: PlanStepSummary[];
  className?: string;
};

type AgentRow = {
  key: string;
  name: string;
  displayName: string;
  info: AgentRunInfo;
};

function statusRank(status: AgentRunInfo['status']): number {
  if (status === 'done') return 5;
  if (status === 'error') return 4;
  if (status === 'running') return 3;
  if (status === 'skipped') return 2;
  return 1;
}

function statusLabel(status: AgentRunInfo['status']): string {
  switch (status) {
    case 'running':
      return '执行中';
    case 'done':
      return '完成';
    case 'error':
      return '异常';
    case 'skipped':
      return '跳过';
    default:
      return '等待';
  }
}

function statusClasses(status: AgentRunInfo['status']): { icon: ReactNode; text: string; bar: string } {
  switch (status) {
    case 'running':
      return {
        icon: <Loader2 size={13} className="animate-spin text-blue-300" />,
        text: 'text-blue-200 bg-blue-500/10',
        bar: 'bg-blue-400',
      };
    case 'done':
      return {
        icon: <CheckCircle2 size={13} className="text-emerald-300" />,
        text: 'text-emerald-200 bg-emerald-500/10',
        bar: 'bg-emerald-400',
      };
    case 'error':
      return {
        icon: <AlertTriangle size={13} className="text-red-300" />,
        text: 'text-red-200 bg-red-500/10',
        bar: 'bg-red-400',
      };
    case 'skipped':
      return {
        icon: <SkipForward size={13} className="text-fin-muted" />,
        text: 'text-fin-muted bg-fin-bg/40',
        bar: 'bg-fin-muted',
      };
    default:
      return {
        icon: <Clock3 size={13} className="text-fin-muted" />,
        text: 'text-fin-muted bg-fin-bg/40',
        bar: 'bg-fin-border',
      };
  }
}

function progressFor(info: AgentRunInfo): number {
  if (info.status === 'done' || info.status === 'error' || info.status === 'skipped') return 100;
  if (typeof info.progress === 'number' && Number.isFinite(info.progress)) {
    return Math.min(100, Math.max(0, Math.round(info.progress)));
  }
  return info.status === 'running' ? 8 : 0;
}

function formatDuration(info: AgentRunInfo): string | null {
  if (typeof info.durationMs === 'number' && Number.isFinite(info.durationMs)) {
    return `${(info.durationMs / 1000).toFixed(1)}s`;
  }
  if (!info.startedAt) return null;
  const start = Date.parse(info.startedAt);
  const end = Date.parse(info.completedAt ?? info.lastEventAt ?? '');
  if (!Number.isFinite(start) || !Number.isFinite(end)) return null;
  return `${Math.max(0, Math.round((end - start) / 1000))}s`;
}

function mergeAgentRows(
  agentStatuses: Record<string, AgentRunInfo>,
  selectedAgents?: string[],
  planSteps?: PlanStepSummary[],
): AgentRow[] {
  const planOrder = new Map<string, number>();
  for (const [index, step] of (planSteps ?? []).entries()) {
    if (step.kind === 'agent') {
      planOrder.set(normalizeAgentName(step.name), index);
    }
  }

  const orderedNames = [
    ...(selectedAgents ?? []),
    ...Object.keys(agentStatuses),
  ];

  const rows = new Map<string, AgentRow>();
  for (const rawName of orderedNames) {
    const normalized = normalizeAgentName(rawName);
    const info = agentStatuses[rawName] ?? agentStatuses[normalized];
    if (!info) continue;

    const existing = rows.get(normalized);
    if (existing && statusRank(existing.info.status) >= statusRank(info.status)) continue;

    rows.set(normalized, {
      key: normalized,
      name: normalized,
      displayName: getAgentDisplayName(normalized),
      info,
    });
  }

  return [...rows.values()].sort((a, b) => {
    const aIndex = planOrder.get(a.name) ?? Number.MAX_SAFE_INTEGER;
    const bIndex = planOrder.get(b.name) ?? Number.MAX_SAFE_INTEGER;
    if (aIndex !== bIndex) return aIndex - bIndex;
    return a.displayName.localeCompare(b.displayName);
  });
}

export function AgentProgressList({
  agentStatuses,
  selectedAgents,
  planSteps,
  className = '',
}: AgentProgressListProps) {
  const agents = useMemo(
    () => mergeAgentRows(agentStatuses, selectedAgents, planSteps),
    [agentStatuses, selectedAgents, planSteps],
  );

  if (agents.length === 0) return null;

  const doneCount = agents.filter((agent) => agent.info.status === 'done').length;
  const activeCount = agents.filter((agent) => agent.info.status === 'running').length;

  return (
    <section className={`space-y-2 ${className}`} aria-label="Agent 执行进度">
      <div className="flex items-center justify-between gap-2 px-1 text-2xs">
        <div className="text-fin-text-secondary">
          Agent 进度
          <span className="ml-1 text-fin-muted">({doneCount}/{agents.length})</span>
        </div>
        {activeCount > 0 && (
          <div className="text-blue-300">{activeCount} 个正在执行</div>
        )}
      </div>

      <div className="divide-y divide-fin-border/50 border-y border-fin-border/50">
        {agents.map(({ key, displayName, info }) => {
          const progress = progressFor(info);
          const duration = formatDuration(info);
          const status = statusClasses(info.status);
          const detail = info.error || info.currentStep || info.fallbackReason || '等待调度';

          return (
            <div key={key} className="py-2">
              <div className="flex items-start gap-2.5">
                <div className="mt-0.5 shrink-0">{status.icon}</div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <div className="min-w-0">
                      <div className="truncate text-xs font-medium text-fin-text">{displayName}</div>
                      <div
                        className={`mt-0.5 truncate text-2xs ${
                          info.status === 'error' ? 'text-red-300' : 'text-fin-muted'
                        }`}
                        title={detail}
                      >
                        {detail}
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-1.5">
                      {info.parallelGroup && (
                        <span className="rounded px-1.5 py-0.5 text-[10px] leading-[14px] text-fin-warning bg-amber-500/10">
                          {info.parallelGroup}
                        </span>
                      )}
                      {duration && <span className="text-[10px] leading-[14px] text-fin-muted">{duration}</span>}
                      <span className={`rounded px-1.5 py-0.5 text-[10px] leading-[14px] ${status.text}`}>
                        {statusLabel(info.status)}
                      </span>
                    </div>
                  </div>
                  <div
                    className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-fin-bg/60"
                    role="progressbar"
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={progress}
                    aria-label={`${displayName} ${statusLabel(info.status)}`}
                  >
                    <div
                      className={`h-full rounded-full transition-all duration-300 ${status.bar}`}
                      style={{ width: `${progress}%` }}
                    />
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

export default AgentProgressList;
