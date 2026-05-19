export type SourceTrustKind = 'snapshot' | 'agent-backed' | 'report-backed' | 'degraded';

export interface SourceTrustInput {
  sourceType?: string | null;
  sourceId?: string | null;
  agentName?: string | null;
  modelGenerated?: boolean | null;
  fallbackUsed?: boolean | null;
  degraded?: boolean | null;
  status?: string | null;
}

export interface SourceTrustBadgeInfo {
  kind: SourceTrustKind;
  label: SourceTrustKind;
  title: string;
  className: string;
}

const BADGE_STYLES: Record<SourceTrustKind, string> = {
  snapshot: 'border-slate-300 bg-slate-100 text-slate-700 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300',
  'agent-backed': 'border-blue-300 bg-blue-50 text-blue-700 dark:border-blue-800 dark:bg-blue-900/25 dark:text-blue-200',
  'report-backed': 'border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-900/25 dark:text-emerald-200',
  degraded: 'border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-900/25 dark:text-amber-200',
};

const BADGE_TITLES: Record<SourceTrustKind, string> = {
  snapshot: '来自快照或规则计算数据',
  'agent-backed': '来自 Agent 执行或 Agent 证据合同',
  'report-backed': '来自研究报告或报告回放',
  degraded: '当前来源存在降级、回退或错误',
};

export const resolveSourceTrustBadge = (input: SourceTrustInput): SourceTrustBadgeInfo => {
  const sourceType = String(input.sourceType || '').toLowerCase();
  const sourceId = String(input.sourceId || '').toLowerCase();
  const status = String(input.status || '').toLowerCase();

  let kind: SourceTrustKind = 'snapshot';
  if (
    input.degraded
    || input.fallbackUsed
    || ['degraded', 'fallback', 'error', 'fail'].includes(status)
  ) {
    kind = 'degraded';
  } else if (sourceType.includes('report') || sourceId.includes('report')) {
    kind = 'report-backed';
  } else if (
    input.agentName
    || input.modelGenerated
    || sourceType.includes('agent')
    || sourceId.startsWith('agent_source')
  ) {
    kind = 'agent-backed';
  }

  return {
    kind,
    label: kind,
    title: BADGE_TITLES[kind],
    className: BADGE_STYLES[kind],
  };
};

interface SourceTrustBadgeProps extends SourceTrustInput {
  className?: string;
}

export function SourceTrustBadge({ className = '', ...input }: SourceTrustBadgeProps) {
  const badge = resolveSourceTrustBadge(input);

  return (
    <span
      title={badge.title}
      className={`inline-flex h-fit items-center rounded-full border px-1.5 py-0.5 text-2xs font-medium ${badge.className} ${className}`.trim()}
    >
      {badge.label}
    </span>
  );
}
