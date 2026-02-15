/**
 * AiPeerSummary - AI-generated peer comparison conclusion from report.
 *
 * If report exists, extracts peer comparison summary.
 * If no report, shows a placeholder prompt.
 */
import type { LatestReportData } from '../../../../hooks/useLatestReport.ts';

interface AiPeerSummaryProps {
  reportData: LatestReportData | null;
  loading?: boolean;
}

function extractPeerSummary(report: Record<string, unknown>): string | null {
  const candidates: unknown[] = [
    report?.peer_summary,
    report?.peer_comparison,
    ((report as Record<string, Record<string, unknown>>)?.agents?.peer_agent as Record<string, unknown>)?.summary,
    ((report as Record<string, Record<string, unknown>>)?.agent_outputs?.peer_agent as Record<string, unknown>)?.summary,
    ((report as Record<string, Record<string, unknown>>)?.agents?.peer_agent as Record<string, unknown>)?.conclusion,
  ];

  for (const candidate of candidates) {
    if (typeof candidate === 'string' && candidate.trim().length > 0) {
      return candidate.trim();
    }
  }

  return null;
}

export function AiPeerSummary({ reportData, loading }: AiPeerSummaryProps) {
  if (loading) {
    return (
      <div className="bg-fin-card border border-fin-border rounded-lg p-4 animate-pulse">
        <div className="h-4 bg-fin-border rounded w-32 mb-3" />
        <div className="space-y-2">
          <div className="h-3 bg-fin-border rounded w-full" />
          <div className="h-3 bg-fin-border rounded w-3/4" />
        </div>
      </div>
    );
  }

  const summary = reportData ? extractPeerSummary(reportData.report) : null;

  return (
    <div className="bg-fin-card border border-fin-border rounded-lg p-4">
      <h4 className="text-sm font-semibold text-fin-text mb-2">AI 同行分析</h4>
      {summary ? (
        <p className="text-sm text-fin-text-secondary leading-relaxed whitespace-pre-wrap">
          {summary}
        </p>
      ) : (
        <p className="text-sm text-fin-muted">
          {reportData
            ? '报告中未包含同行对比分析'
            : '生成报告以获取 AI 同行分析'}
        </p>
      )}
    </div>
  );
}

export default AiPeerSummary;
