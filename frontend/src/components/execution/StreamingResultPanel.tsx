/**
 * StreamingResultPanel — displays real-time execution progress and results.
 *
 * States:
 *   null/empty → placeholder
 *   running    → agent status bar + progress + streaming text + cancel
 *   done       → ReportView (if report) or final text + bridge buttons
 *   error      → error message + fallback reasons
 *   cancelled  → cancelled notice
 *
 * Bridge buttons (manual, one-click, no auto-write):
 *   brief           → "发送摘要到聊天" (secondary)
 *   investment_report → "继续追问" (primary, switches to chat with context)
 */
import React from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  Loader2,
  MessageSquare,
  Send,
  StopCircle,
  XCircle,
} from 'lucide-react';

import { useExecutionStore } from '../../store/executionStore';
import { useStore } from '../../store/useStore';
import { ReportView } from '../report/ReportView';
import type { AgentRunInfo } from '../../types/execution';

// --- Constants ---

const AGENT_DISPLAY_ORDER = [
  'price_agent',
  'news_agent',
  'fundamental_agent',
  'technical_agent',
  'macro_agent',
  'deep_search_agent',
];

// --- Sub-components ---

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
    default: // pending
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

  // Include any dynamically-appended agents not in fixed order
  const extra = Object.values(agents).filter(
    (a) => !AGENT_DISPLAY_ORDER.includes(a.name),
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

// --- Props ---

interface StreamingResultPanelProps {
  runId: string | null;
  className?: string;
  compact?: boolean;
  /** Callback to navigate to chat view (for "继续追问" bridge). */
  onNavigateToChat?: () => void;
}

// --- Component ---

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
  const markBridged = useExecutionStore((s) => s.markBridged);
  const addMessage = useStore((s) => s.addMessage);

  // --- Bridge: 发送摘要到聊天 (brief mode) ---
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

  // --- Bridge: 继续追问 (report mode) ---
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

  // --- Empty state ---
  if (!runId || !run) {
    return (
      <div
        className={`flex items-center justify-center text-fin-muted text-sm p-8 ${className}`}
      >
        暂无执行结果
      </div>
    );
  }

  // --- Running ---
  if (run.status === 'running') {
    return (
      <div className={`flex flex-col gap-3 ${className}`}>
        <AgentStatusBar agents={run.agentStatuses} compact={compact} />

        {/* Progress */}
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

        {/* Streaming text */}
        {run.streamedContent && (
          <div
            className={`text-sm text-fin-text whitespace-pre-wrap break-words overflow-y-auto ${
              compact ? 'max-h-48' : 'max-h-96'
            } border border-fin-border rounded-lg p-3 bg-fin-bg/50`}
          >
            {run.streamedContent}
          </div>
        )}

        {/* Cancel */}
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

  // --- Done ---
  if (run.status === 'done') {
    const isReport = run.outputMode === 'investment_report';
    const isBridged = run.bridgedToChat === true;
    const isDashboardRun = run.source?.startsWith('dashboard');
    const inlineReport = !isDashboardRun ? run.report : null;

    return (
      <div className={`flex flex-col gap-3 ${className}`}>
        {/* Result content */}
        {inlineReport ? (
          <ReportView report={inlineReport} />
        ) : (
          <>
            <div className="flex items-center gap-2 text-xs text-emerald-400">
              <CheckCircle2 size={14} />
              {isDashboardRun ? '执行完成，结果已同步到仪表盘' : '执行完成'}
            </div>
            {run.streamedContent && (
              <div className="text-sm text-fin-text whitespace-pre-wrap break-words overflow-y-auto max-h-96 border border-fin-border rounded-lg p-3 bg-fin-bg/50">
                {run.streamedContent}
              </div>
            )}
          </>
        )}

        {/* Bridge buttons */}
        {!isDashboardRun && (
          <div className="flex items-center gap-2 pt-2 border-t border-fin-border/50">
          {isReport ? (
            /* 投资报告 → 主按钮：继续追问 */
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
            /* Brief 分析 → 次级按钮：发送摘要到聊天 */
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
      </div>
    );
  }

  // --- Error ---
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
      </div>
    );
  }

  // --- Cancelled ---
  return (
    <div
      className={`flex items-center gap-2 text-xs text-fin-muted ${className}`}
    >
      <XCircle size={14} />
      执行已取消
    </div>
  );
};
