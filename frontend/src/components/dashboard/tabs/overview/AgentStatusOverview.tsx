import { useMemo } from 'react';

import type { LatestReportData } from '../../../../hooks/useLatestReport';
import { CardInfoTip } from '../../../ui/CardInfoTip';
import { asRecord } from '../../../../utils/record';

type AgentStatusKind = 'success' | 'fallback' | 'error' | 'not_run' | 'unknown';
type NotRunReasonKind = 'policy' | 'depth' | 'error' | 'unknown' | null;
type DiagnosticSeverity = 'info' | 'warn' | 'error';
type DiagnosticKind = 'execution' | 'evidence';

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

interface DiagnosticItem {
  id: string;
  title: string;
  detail: string;
  severity: DiagnosticSeverity;
  kind: DiagnosticKind;
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

const DIAGNOSTIC_STYLE: Record<DiagnosticSeverity, { dot: string; text: string }> = {
  info: { dot: 'bg-fin-muted', text: 'text-fin-muted' },
  warn: { dot: 'bg-fin-warning', text: 'text-fin-warning' },
  error: { dot: 'bg-fin-danger', text: 'text-fin-danger' },
};

const normalizeStatus = (value: unknown): AgentStatusKind => {
  const raw = String(value || '').trim().toLowerCase();
  if (raw === 'success') return 'success';
  if (raw === 'fallback') return 'fallback';
  if (raw === 'error') return 'error';
  if (raw === 'not_run' || raw === 'skipped') return 'not_run';
  return 'unknown';
};

const asString = (value: unknown): string => (typeof value === 'string' ? value.trim() : '');

const asStringList = (value: unknown): string[] => (
  Array.isArray(value)
    ? value.map((item) => asString(item)).filter(Boolean)
    : []
);

const asNumberOrNull = (value: unknown): number | null => {
  const num = Number(value);
  if (!Number.isFinite(num)) return null;
  return num <= 1 ? Math.max(0, Math.min(1, num)) : Math.max(0, Math.min(1, num / 100));
};

const containsAny = (text: string, candidates: string[]): boolean => (
  candidates.some((token) => text.includes(token))
);

const EVIDENCE_QUALITY_KEYWORDS = [
  '质量门槛',
  '证据',
  '引用',
  'citation',
  '10-k',
  '10-q',
  '业绩电话会',
  '纪要',
  '路透',
  'reuters',
  'bloomberg',
  'wsj',
  'ft',
  'cnbc',
  'yahoo',
  '摘录',
];

const EXECUTION_DIAGNOSTIC_KEYWORDS = [
  'agent',
  'diagnostic',
  'orchestration',
  'policy',
  'analysis_depth',
  'conflict',
  '未运行',
  '未执行',
  '冲突',
  '裁决',
  '可信度受限',
  '调度',
];

const isEvidenceQualityText = (text: string): boolean => (
  containsAny(text.toLowerCase(), EVIDENCE_QUALITY_KEYWORDS)
);

const isExecutionDiagnosticText = (text: string): boolean => {
  const lower = text.toLowerCase();
  return containsAny(lower, EXECUTION_DIAGNOSTIC_KEYWORDS);
};

const isOperationalDiagnosticText = (text: string): boolean => (
  isExecutionDiagnosticText(text) || isEvidenceQualityText(text)
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

function buildDiagnostics(
  rows: AgentViewModel[],
  reportData: LatestReportData | null | undefined,
): DiagnosticItem[] {
  const diagnostics: DiagnosticItem[] = [];
  const dedupe = new Set<string>();

  const append = (
    title: string,
    detail: string,
    severity: DiagnosticSeverity,
    kind: DiagnosticKind,
  ) => {
    const cleanTitle = title.trim();
    const cleanDetail = detail.trim();
    if (!cleanTitle || !cleanDetail) return;
    const key = `${cleanTitle}::${cleanDetail}`;
    if (dedupe.has(key)) return;
    dedupe.add(key);
    diagnostics.push({
      id: `diag-${diagnostics.length + 1}`,
      title: cleanTitle,
      detail: cleanDetail,
      severity,
      kind,
    });
  };

  rows.forEach((row) => {
    if (row.status === 'error') {
      append(`${row.label} 执行失败`, row.reasonText || '执行失败', 'error', 'execution');
      return;
    }
    if (row.status === 'not_run') {
      append(`${row.label} 未运行`, row.reasonText || '未调度', 'warn', 'execution');
      return;
    }
    if (row.status === 'fallback') {
      append(`${row.label} 降级执行`, row.reasonText || '采用降级路径', 'info', 'execution');
    }
  });

  const report = asRecord(reportData?.report);
  const rawRiskEntries = [
    ...asStringList(report?.risks),
    ...asStringList(report?.risk_factors),
  ];

  rawRiskEntries
    .filter((text) => isOperationalDiagnosticText(text))
    .slice(0, 4)
    .forEach((text) => append(
      isEvidenceQualityText(text) ? '证据质量诊断' : '跨智能体诊断',
      text,
      'warn',
      isEvidenceQualityText(text) ? 'evidence' : 'execution',
    ));

  return diagnostics.slice(0, 6);
}

function buildDiagnosticTipContent(item: DiagnosticItem) {
  const impact = item.kind === 'evidence'
    ? '影响：该条结论证据不足，建议仅作参考，避免直接用于交易决策。'
    : '影响：对应 Agent 结果不可用或降级，综合结论完整性会下降。';
  const recovery = item.kind === 'evidence'
    ? '恢复：补齐 10-K/10-Q/业绩会与权威媒体摘录后重跑分析。'
    : '恢复：检查调度策略与分析深度后重新执行工作台分析。';

  return (
    <div className="space-y-1">
      <div>原因：{item.detail}</div>
      <div>{impact}</div>
      <div>{recovery}</div>
    </div>
  );
}

export function AgentStatusOverview({ reportData }: AgentStatusOverviewProps) {
  const rows = useMemo(() => buildAgentRows(reportData), [reportData]);
  const diagnostics = useMemo(() => buildDiagnostics(rows, reportData), [rows, reportData]);

  return (
    <div className="flex flex-col p-4 bg-fin-card rounded-xl border border-fin-border">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-medium text-fin-muted flex items-center gap-1">
          Agent 执行总览
          <CardInfoTip content="展示各 Agent 执行状态、置信度与执行诊断信息" />
        </span>
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

      {diagnostics.length > 0 && (
        <div className="mt-3 pt-3 border-t border-fin-border/70 space-y-2">
          <div className="text-2xs font-medium text-fin-muted">执行诊断</div>
          {diagnostics.map((item) => {
            const style = DIAGNOSTIC_STYLE[item.severity];
            return (
              <div key={item.id} className="group/diag flex items-start gap-2">
                <span className={`w-2 h-2 rounded-full shrink-0 mt-1 ${style.dot}`} />
                <div className="flex-1 min-w-0">
                  <div className={`text-xs ${style.text}`}>{item.title}</div>
                  <div className="text-2xs text-fin-muted leading-relaxed line-clamp-2">{item.detail}</div>
                </div>
                <CardInfoTip
                  icon="alert"
                  size={13}
                  className="shrink-0 mt-0.5"
                  content={buildDiagnosticTipContent(item)}
                />
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default AgentStatusOverview;
