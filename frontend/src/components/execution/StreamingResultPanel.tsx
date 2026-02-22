/**
 * StreamingResultPanel - displays real-time execution progress and results.
 *
 * States:
 * - null/empty: placeholder
 * - running: agent status bar + progress + streaming text + cancel
 * - interrupted: confirmation card + resume/cancel actions
 * - done: ReportView (if report) or final text + bridge buttons
 * - error: error message + fallback reasons
 * - cancelled: cancelled notice
 */
import React from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  Loader2,
  MessageSquare,
  PauseCircle,
  Send,
  StopCircle,
  XCircle,
} from 'lucide-react';

import { useExecutionStore } from '../../store/executionStore';
import { useStore } from '../../store/useStore';
import { ReportView } from '../report/ReportView';
import { AgentTimeline } from './AgentTimeline';
import { InterruptCard } from './InterruptCard';
import type { AgentRunInfo, ExecutionRun } from '../../types/execution';

const AGENT_DISPLAY_ORDER = [
  'price_agent',
  'news_agent',
  'fundamental_agent',
  'technical_agent',
  'macro_agent',
  'deep_search_agent',
];

type KeySectionIssueView = {
  section: string;
  actual?: unknown;
  threshold?: unknown;
  issue?: string;
};

function formatQualityValue(value: unknown): string {
  if (typeof value === 'number' && Number.isFinite(value)) {
    if (Math.abs(value) <= 1) return value.toFixed(4);
    return Number.isInteger(value) ? String(value) : value.toFixed(2);
  }
  if (typeof value === 'string') {
    const text = value.trim();
    return text || 'N/A';
  }
  if (typeof value === 'boolean') {
    return value ? 'true' : 'false';
  }
  return 'N/A';
}

function parseLegacyKeySectionIssue(raw: string): KeySectionIssueView {
  const text = raw.trim();
  const match = text.match(/^(.*)\s+refs<\s*([0-9]+)\s*$/i);
  if (match) {
    return {
      section: match[1].trim() || 'Unknown section',
      threshold: Number(match[2]),
      issue: text,
    };
  }
  return { section: text || 'Unknown section', issue: text };
}

function extractStructuredKeySectionIssues(
  details: Record<string, unknown>,
  field: string,
): KeySectionIssueView[] {
  const issueViews: KeySectionIssueView[] = [];
  const structured = details[field];
  if (!Array.isArray(structured)) return issueViews;
  for (const item of structured) {
    if (!item || typeof item !== 'object') continue;
    const row = item as Record<string, unknown>;
    const section = typeof row.section === 'string' ? row.section.trim() : '';
    if (!section) continue;
    issueViews.push({
      section,
      actual: row.actual,
      threshold: row.threshold,
      issue: typeof row.issue === 'string' ? row.issue : undefined,
    });
  }
  return issueViews;
}

function extractKeySectionIssues(run: ExecutionRun): {
  blockIssues: KeySectionIssueView[];
  warnIssues: KeySectionIssueView[];
} {
  const details = run.qualityDetails && typeof run.qualityDetails === 'object'
    ? run.qualityDetails
    : {};
  const detailRecord = details as Record<string, unknown>;

  const blockIssues = extractStructuredKeySectionIssues(detailRecord, 'key_section_block_issue_details');
  const warnIssues = extractStructuredKeySectionIssues(detailRecord, 'key_section_warn_issue_details');
  if (blockIssues.length > 0 || warnIssues.length > 0) {
    return { blockIssues, warnIssues };
  }

  const legacy = detailRecord.key_section_issues;
  if (!Array.isArray(legacy)) {
    return { blockIssues: [], warnIssues: [] };
  }
  const legacyIssues = legacy
    .filter((item): item is string => typeof item === 'string')
    .map((item) => parseLegacyKeySectionIssue(item));
  return { blockIssues: legacyIssues, warnIssues: [] };
}

function AgentStatusIcon({ status }: { status: AgentRunInfo['status'] }) {
  switch (status) {
    case 'running':
      return <Loader2 size={12} className="animate-spin text-blue-400" />;
    case 'done':
      return <CheckCircle2 size={12} className="text-emerald-400" />;
    case 'error':
      return <XCircle size={12} className="text-red-400" />;
    case 'skipped':
      return <span className="w-3 h-3 rounded-full bg-gray-500 inline-block" />;
    default:
      return <span className="w-3 h-3 rounded-full border border-fin-border inline-block" />;
  }
}

function AgentStatusBar({
  agents,
  compact,
}: {
  agents: Record<string, AgentRunInfo>;
  compact?: boolean;
}) {
  const ordered = AGENT_DISPLAY_ORDER
    .filter((name) => agents[name])
    .map((name) => agents[name]);
  const extra = Object.values(agents).filter(
    (agent) => !AGENT_DISPLAY_ORDER.includes(agent.name),
  );
  const all = [...ordered, ...extra];

  if (all.length === 0) return null;

  return (
    <div className={`flex flex-wrap ${compact ? 'gap-1.5' : 'gap-2'}`}>
      {all.map((agent) => (
        <div
          key={agent.name}
          className="flex items-center gap-1 text-2xs text-fin-muted"
          title={agent.error ?? agent.name}
        >
          <AgentStatusIcon status={agent.status} />
          {!compact && (
            <span className="truncate max-w-20">
              {agent.name.replace(/_agent$/, '')}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

interface StreamingResultPanelProps {
  runId: string | null;
  className?: string;
  compact?: boolean;
  onNavigateToChat?: () => void;
}

export const StreamingResultPanel: React.FC<StreamingResultPanelProps> = ({
  runId,
  className = '',
  compact = false,
  onNavigateToChat,
}) => {
  const run = useExecutionStore((s) => {
    if (!runId) return null;
    return (
      s.activeRuns.find((r) => r.runId === runId) ??
      s.recentRuns.find((r) => r.runId === runId) ??
      null
    );
  });

  const cancelExecution = useExecutionStore((s) => s.cancelExecution);
  const resumeExecution = useExecutionStore((s) => s.resumeExecution);
  const markBridged = useExecutionStore((s) => s.markBridged);
  const addMessage = useStore((s) => s.addMessage);

  const handleSendSummaryToChat = () => {
    if (!run || run.bridgedToChat || run.status !== 'done') return;

    const ticker = run.tickers[0] || '';
    const summary = run.streamedContent || '(无内容)';

    addMessage({
      id: `bridge-${run.runId}`,
      role: 'assistant',
      content: `**${ticker ? `${ticker} ` : ''}快速分析摘要**\n\n${summary}`,
      timestamp: Date.now(),
      relatedTicker: ticker || undefined,
      via: 'mini',
      data_origin: 'execution_bridge',
    });

    markBridged(run.runId);
  };

  const handleContinueInChat = () => {
    if (!run || run.bridgedToChat || run.status !== 'done') return;

    const ticker = run.tickers[0] || '';
    const reportTitle = run.report?.title || `${ticker} 投资报告`;
    const reportSummary = run.report?.summary || run.streamedContent?.slice(0, 500) || '';

    addMessage({
      id: `bridge-${run.runId}`,
      role: 'assistant',
      content: `**${reportTitle}**\n\n${reportSummary}\n\n---\n*报告已生成，可在此继续追问。*`,
      timestamp: Date.now(),
      relatedTicker: ticker || undefined,
      report: run.report ?? undefined,
      via: 'main',
      data_origin: 'execution_bridge',
    });

    markBridged(run.runId);
    onNavigateToChat?.();
  };

  const handleContinueBlockedInChat = () => {
    if (!run || run.bridgedToChat || run.status !== 'done') return;

    const ticker = run.tickers[0] || '';
    const reportTitle = run.report?.title || `${ticker} 分析草稿`;
    const reportSummary = run.report?.summary || run.streamedContent?.slice(0, 500) || '';

    addMessage({
      id: `bridge-${run.runId}`,
      role: 'assistant',
      content: `**${reportTitle}（草稿，未发布）**\n\n${reportSummary}\n\n---\n*该结果未通过质量门禁，仅用于继续讨论，不可直接发布或复用。*`,
      timestamp: Date.now(),
      relatedTicker: ticker || undefined,
      report: run.report ?? undefined,
      via: 'main',
      data_origin: 'execution_bridge',
    });

    markBridged(run.runId);
    onNavigateToChat?.();
  };

  if (!runId || !run) {
    return (
      <div className={`flex items-center justify-center text-fin-muted text-sm p-8 ${className}`}>
        暂无执行结果
      </div>
    );
  }

  if (run.status === 'running') {
    return (
      <div className={`flex flex-col gap-3 ${className}`}>
        <AgentStatusBar agents={run.agentStatuses} compact={compact} />

        <div className="space-y-1">
          <div className="flex items-center justify-between text-xs">
            <span className="text-fin-muted truncate">
              {run.currentStep ?? '执行中...'}
            </span>
            <span className="text-blue-400 shrink-0">{run.progress}%</span>
          </div>
          <div className="h-1.5 rounded-full bg-fin-border overflow-hidden">
            <div
              className="h-full rounded-full bg-blue-500 transition-all duration-300"
              style={{ width: `${run.progress}%` }}
            />
          </div>
        </div>

        {run.fallbackReasons.length > 0 && (
          <div className="text-2xs text-amber-300 bg-amber-950/20 border border-amber-900/40 rounded-lg px-3 py-2">
            部分 Agent 已降级（主流程继续）：{run.fallbackReasons[run.fallbackReasons.length - 1]}
          </div>
        )}

        {run.streamedContent && (
          <div
            className={`text-sm text-fin-text whitespace-pre-wrap break-words overflow-y-auto ${
              compact ? 'max-h-48' : 'max-h-96'
            } border border-fin-border rounded-lg p-3 bg-fin-bg/50`}
          >
            {run.streamedContent}
          </div>
        )}

        <AgentTimeline timeline={run.timeline} compact={compact} />

        <button
          type="button"
          onClick={() => cancelExecution(run.runId)}
          className="flex items-center gap-1.5 text-xs text-fin-muted hover:text-red-400 transition-colors self-start"
        >
          <StopCircle size={14} />
          取消执行
        </button>
      </div>
    );
  }

  if (run.status === 'interrupted') {
    const interruptData = run.interruptData;
    return (
      <div className={`flex flex-col gap-3 ${className}`}>
        <div className="flex items-center gap-2 text-xs text-amber-300">
          <PauseCircle size={14} />
          等待确认后继续执行
        </div>

        {interruptData?.thread_id ? (
          <InterruptCard
            data={interruptData}
            onResume={(_threadId, resumeValue) => {
              void resumeExecution(run.runId, resumeValue);
            }}
            onCancel={() => cancelExecution(run.runId)}
          />
        ) : (
          <div className="text-xs text-amber-200 bg-amber-950/20 border border-amber-900/40 rounded-lg px-3 py-2">
            当前执行已中断，但缺少恢复上下文。请重新发起一次执行。
          </div>
        )}

        <AgentTimeline timeline={run.timeline} compact={compact} />
      </div>
    );
  }

  if (run.status === 'done') {
    const isReport = run.outputMode === 'investment_report';
    const isBridged = run.bridgedToChat === true;
    const isDashboardRun = run.source?.startsWith('dashboard');
    const isQualityBlocked = run.qualityBlocked === true;
    const inlineReport = (!isDashboardRun && !isQualityBlocked) ? run.report : null;
    const qualityReasons = run.qualityReasons ?? [];
    const blockedReasons = qualityReasons.filter((item) => item.severity === 'block');
    const warningReasons = qualityReasons.filter((item) => item.severity !== 'block');
    const blockedReasonCodes = run.blockedReasonCodes ?? [];
    const { blockIssues: keySectionBlockIssues, warnIssues: keySectionWarnIssues } = extractKeySectionIssues(run);

    return (
      <div className={`flex flex-col gap-3 ${className}`}>
        {inlineReport ? (
          <ReportView report={inlineReport} />
        ) : (
          <>
            <div className={`flex items-center gap-2 text-xs ${isQualityBlocked ? 'text-amber-300' : 'text-emerald-400'}`}>
              {isQualityBlocked ? <AlertTriangle size={14} /> : <CheckCircle2 size={14} />}
              {isQualityBlocked
                ? '执行完成，但报告被质量门禁拦截（未发布）'
                : (isDashboardRun ? '执行完成，结果已同步到仪表盘' : '执行完成')}
            </div>

            {isQualityBlocked && (
              <div className="rounded-lg border border-amber-900/40 bg-amber-950/20 px-3 py-2 text-xs text-amber-100 space-y-1">
                {blockedReasons.length > 0 ? (
                  blockedReasons.map((item) => (
                    <div key={`${item.code}:${item.metric}`} className="space-y-0.5">
                      <div>[{item.code}] {item.message}</div>
                      {(item.actual !== undefined || item.threshold !== undefined) && (
                        <div className="text-2xs text-amber-200">
                          actual: {formatQualityValue(item.actual)} / threshold: {formatQualityValue(item.threshold)}
                        </div>
                      )}
                    </div>
                  ))
                ) : blockedReasonCodes.length > 0 ? (
                  <div>原因代码: {blockedReasonCodes.join(', ')}</div>
                ) : (
                  <div>未提供详细原因，请在质量详情中查看门禁规则。</div>
                )}

                {keySectionBlockIssues.length > 0 && (
                  <div className="mt-2 border-t border-amber-900/40 pt-2 space-y-1">
                    <div className="text-amber-200">失败章节（硬门禁）：</div>
                    {keySectionBlockIssues.map((issue, index) => (
                      <div key={`${issue.section}:${index}`} className="text-2xs">
                        {issue.section} | actual: {formatQualityValue(issue.actual)} / threshold: {formatQualityValue(issue.threshold)}
                      </div>
                    ))}
                  </div>
                )}

                {(warningReasons.length > 0 || keySectionWarnIssues.length > 0) && (
                  <div className="mt-2 border-t border-amber-900/40 pt-2 space-y-1">
                    <div className="text-amber-200">告警项（不拦截）：</div>
                    {warningReasons.map((item) => (
                      <div key={`warn:${item.code}:${item.metric}`} className="space-y-0.5">
                        <div>[{item.code}] {item.message}</div>
                        {(item.actual !== undefined || item.threshold !== undefined) && (
                          <div className="text-2xs text-amber-200">
                            actual: {formatQualityValue(item.actual)} / threshold: {formatQualityValue(item.threshold)}
                          </div>
                        )}
                      </div>
                    ))}
                    {keySectionWarnIssues.map((issue, index) => (
                      <div key={`warn-section:${issue.section}:${index}`} className="text-2xs">
                        {issue.section} | actual: {formatQualityValue(issue.actual)} / threshold: {formatQualityValue(issue.threshold)}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {run.streamedContent && (
              <div className="text-sm text-fin-text whitespace-pre-wrap break-words overflow-y-auto max-h-96 border border-fin-border rounded-lg p-3 bg-fin-bg/50">
                {run.streamedContent}
              </div>
            )}
          </>
        )}

        {!isDashboardRun && !isQualityBlocked && (
          <div className="flex items-center gap-2 pt-2 border-t border-fin-border/50">
            {isReport ? (
              <button
                type="button"
                onClick={handleContinueInChat}
                disabled={isBridged}
                className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg transition-colors ${
                  isBridged
                    ? 'bg-fin-bg text-fin-muted cursor-not-allowed'
                    : 'bg-fin-primary text-white hover:bg-fin-primary/90'
                }`}
              >
                <MessageSquare size={12} />
                {isBridged ? '已发送到聊天' : '继续追问'}
              </button>
            ) : (
              <button
                type="button"
                onClick={handleSendSummaryToChat}
                disabled={isBridged}
                className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg border transition-colors ${
                  isBridged
                    ? 'border-fin-border text-fin-muted cursor-not-allowed'
                    : 'border-fin-border text-fin-text-secondary hover:text-fin-primary hover:border-fin-primary/50'
                }`}
              >
                <Send size={12} />
                {isBridged ? '已发送到聊天' : '发送摘要到聊天'}
              </button>
            )}
          </div>
        )}

        {isQualityBlocked && run.allowContinueWhenBlocked && (
          <div className="flex items-center gap-2 pt-2 border-t border-fin-border/50">
            <button
              type="button"
              onClick={handleContinueBlockedInChat}
              disabled={isBridged}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg transition-colors ${
                isBridged
                  ? 'bg-fin-bg text-fin-muted cursor-not-allowed'
                  : 'bg-fin-primary text-white hover:bg-fin-primary/90'
              }`}
            >
              <MessageSquare size={12} />
              {isBridged ? '已发送到聊天' : '继续生成（不发布）'}
            </button>
          </div>
        )}

        <AgentTimeline timeline={run.timeline} compact={compact} />
      </div>
    );
  }

  if (run.status === 'error') {
    return (
      <div className={`flex flex-col gap-3 ${className}`}>
        <div className="flex items-center gap-2 text-xs text-red-400">
          <AlertTriangle size={14} />
          执行失败
        </div>
        {run.error && (
          <div className="text-xs text-red-300 bg-red-950/30 border border-red-900/30 rounded-lg p-3">
            {run.error}
          </div>
        )}
        {run.fallbackReasons.length > 0 && (
          <div className="text-2xs text-fin-muted space-y-0.5">
            {run.fallbackReasons.map((reason, i) => (
              <div key={`fallback-${i}`}>{reason}</div>
            ))}
          </div>
        )}
        <AgentTimeline timeline={run.timeline} compact={compact} />
      </div>
    );
  }

  return (
    <div className={`flex items-center gap-2 text-xs text-fin-muted ${className}`}>
      <XCircle size={14} />
      执行已取消
    </div>
  );
};
