/**
 * AiNewsSummaryCard - Displays AI-generated news summary from report.
 *
 * If a report exists, extracts the news agent summary.
 * If no report, shows a placeholder prompt.
 */
import type { LatestReportData } from '../../../../hooks/useLatestReport.ts';

interface AiNewsSummaryCardProps {
  reportData: LatestReportData | null;
  loading?: boolean;
}

/**
 * Attempt to extract a news-related summary from the report object.
 * The report structure varies, so we try multiple known paths.
 */
function extractNewsSummary(report: Record<string, unknown>): string | null {
  // Try common report paths for news agent output
  const candidates: unknown[] = [
    (report as Record<string, unknown>)?.news_summary,
    (report as Record<string, unknown>)?.news_agent_output,
    ((report as Record<string, Record<string, unknown>>)?.agents?.news_agent as Record<string, unknown>)?.summary,
    ((report as Record<string, Record<string, unknown>>)?.agent_outputs?.news_agent as Record<string, unknown>)?.summary,
    (report as Record<string, unknown>)?.summary,
  ];

  for (const candidate of candidates) {
    if (typeof candidate === 'string' && candidate.trim().length > 0) {
      return candidate.trim();
    }
  }

  return null;
}

export function AiNewsSummaryCard({ reportData, loading }: AiNewsSummaryCardProps) {
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

  const summary = reportData ? extractNewsSummary(reportData.report) : null;

  return (
    <div className="bg-fin-card border border-fin-border rounded-lg p-4">
      <h4 className="text-sm font-semibold text-fin-text mb-2">AI 新闻摘要</h4>
      {summary ? (
        <p className="text-sm text-fin-text-secondary leading-relaxed whitespace-pre-wrap">
          {summary}
        </p>
      ) : (
        <p className="text-sm text-fin-muted">
          {reportData
            ? '报告中未包含新闻摘要信息'
            : '执行分析以获取 AI 新闻摘要'}
        </p>
      )}
    </div>
  );
}

export default AiNewsSummaryCard;
