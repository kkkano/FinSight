import { useMemo } from 'react';

import type { LatestReportData } from '../../../../hooks/useLatestReport';

type AgentStatusKind = 'success' | 'fallback' | 'error' | 'not_run' | 'unknown';
type NotRunReasonKind = 'policy' | 'depth' | 'error' | 'unknown' | null;

interface AgentDefinition {
  key: string;
  label: string;
}

interface AgentViewModel {
  key: string;
  label: string;
  status: AgentStatusKind;
  confidence: number | null;
  reasonKind: NotRunReasonKind;
  reasonText: string | null;
}

interface AgentStatusOverviewProps {
  reportData?: LatestReportData | null;
}

const AGENT_DEFINITIONS: AgentDefinition[] = [
  { key: 'price_agent', label: '价格' },
  { key: 'news_agent', label: '新闻' },
  { key: 'fundamental_agent', label: '基本面' },
  { key: 'technical_agent', label: '技术面' },
  { key: 'macro_agent', label: '宏观' },
  { key: 'risk_agent', label: '风险' },
  { key: 'deep_search_agent', label: '深度检索' },
];

const STATUS_STYLE: Record<AgentStatusKind, { dot: string; text: string; label: string }> = {
  success: { dot: 'bg-fin-success', text: 'text-fin-success', label: '完成' },
  fallback: { dot: 'bg-fin-warning', text: 'text-fin-warning', label: '降级' },
  error: { dot: 'bg-fin-danger', text: 'text-fin-danger', label: '失败' },
  not_run: { dot: 'bg-fin-muted', text: 'text-fin-muted', label: '未运行' },
  unknown: { dot: 'bg-fin-muted', text: 'text-fin-muted', label: '未知' },
};

const REASON_LABEL: Record<Exclude<NotRunReasonKind, null>, string> = {
  policy: '策略过滤',
  depth: '深度策略',
  error: '执行异常',
  unknown: '未调度',
};

const normalizeStatus = (value: unknown): AgentStatusKind => {
  const raw = String(value || '').trim().toLowerCase();
  if (raw === 'success') return 'success';
  if (raw === 'fallback') return 'fallback';
  if (raw === 'error') return 'error';
  if (raw === 'not_run' || raw === 'skipped') return 'not_run';
  return 'unknown';
};

const asRecord = (value: unknown): Record<string, unknown> | null => (
  value && typeof value === 'object' ? (value as Record<string, unknown>) : null
);

const asString = (value: unknown): string => (typeof value === 'string' ? value.trim() : '');

const asNumberOrNull = (value: unknown): number | null => {
  const num = Number(value);
  if (!Number.isFinite(num)) return null;
  return num <= 1 ? Math.max(0, Math.min(1, num)) : Math.max(0, Math.min(1, num / 100));
};

const containsAny = (text: string, candidates: string[]): boolean => (
  candidates.some((token) => text.includes(token))
);

function buildAgentRows(reportData: LatestReportData | null | undefined): AgentViewModel[] {
  const report = asRecord(reportData?.report);
  const agentStatus = asRecord(report?.agent_status);
  const agentDiagnostics = asRecord(report?.agent_diagnostics);
  const meta = asRecord(report?.meta);
  const graphTrace = asRecord(meta?.graph_trace);
  const tracePolicy = asRecord(graphTrace?.policy);
  const traceAgentSelection = asRecord(tracePolicy?.agent_selection);

  const allowedAgents = new Set(
    Array.isArray(tracePolicy?.allowed_agents)
      ? tracePolicy?.allowed_agents.filter((item): item is string => typeof item === 'string')
      : [],
  );
  const removedByPrefs = new Set(
    Array.isArray(traceAgentSelection?.removed_by_prefs)
      ? traceAgentSelection?.removed_by_prefs.filter((item): item is string => typeof item === 'string')
      : [],
  );
  const removedByDepth = new Set(
    Array.isArray(traceAgentSelection?.removed_by_analysis_depth)
      ? traceAgentSelection?.removed_by_analysis_depth.filter((item): item is string => typeof item === 'string')
      : [],
  );

  return AGENT_DEFINITIONS.map((definition) => {
    const statusNode = asRecord(agentStatus?.[definition.key]);
    const diagnosticsNode = asRecord(agentDiagnostics?.[definition.key]);

    const status = normalizeStatus(statusNode?.status ?? diagnosticsNode?.status ?? 'not_run');
    const confidence = asNumberOrNull(statusNode?.confidence ?? diagnosticsNode?.confidence);

    if (status === 'error') {
      const errorText = asString(statusNode?.error) || asString(diagnosticsNode?.error_stage) || '执行失败';
      return {
        key: definition.key,
        label: definition.label,
        status,
        confidence,
        reasonKind: 'error',
        reasonText: errorText,
      };
    }

    if (status !== 'not_run') {
      return {
        key: definition.key,
        label: definition.label,
        status,
        confidence,
        reasonKind: null,
        reasonText: null,
      };
    }

    const skippedReason = asString(statusNode?.skipped_reason)
      || asString(statusNode?.fallback_reason)
      || asString(diagnosticsNode?.fallback_reason);
    const skippedReasonLower = skippedReason.toLowerCase();

    let reasonKind: NotRunReasonKind = 'unknown';
    if (
      removedByDepth.has(definition.key)
      || containsAny(skippedReasonLower, ['analysis_depth', 'deep_research', 'escalation'])
      || statusNode?.escalation_not_needed === true
    ) {
      reasonKind = 'depth';
    } else if (removedByPrefs.has(definition.key) || !allowedAgents.has(definition.key)) {
      reasonKind = 'policy';
    }

    return {
      key: definition.key,
      label: definition.label,
      status,
      confidence,
      reasonKind,
      reasonText: skippedReason || REASON_LABEL[reasonKind],
    };
  });
}

export function AgentStatusOverview({ reportData }: AgentStatusOverviewProps) {
  const rows = useMemo(() => buildAgentRows(reportData), [reportData]);

  return (
    <div className="flex flex-col p-4 bg-fin-card rounded-xl border border-fin-border">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-medium text-fin-muted">Agent 执行总览</span>
        <span className="text-2xs text-fin-muted">{rows.length} agents</span>
      </div>

      <div className="space-y-2">
        {rows.map((row) => {
          const style = STATUS_STYLE[row.status];
          return (
            <div key={row.key} className="rounded-lg border border-fin-border/70 p-2">
              <div className="flex items-center gap-2">
                <span className={`w-2 h-2 rounded-full shrink-0 ${style.dot}`} />
                <span className="text-sm text-fin-text flex-1">{row.label}</span>
                {row.confidence != null && (
                  <span className="text-2xs text-fin-muted tabular-nums">
                    {Math.round(row.confidence * 100)}%
                  </span>
                )}
                <span className={`text-2xs ${style.text}`}>{style.label}</span>
              </div>
              {row.reasonKind && (
                <div className="mt-1 text-2xs text-fin-muted">
                  {REASON_LABEL[row.reasonKind]}：{row.reasonText || '--'}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default AgentStatusOverview;
