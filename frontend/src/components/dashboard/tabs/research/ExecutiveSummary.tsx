/**
 * ExecutiveSummary - Display report executive summary with expand/collapse.
 *
 * Shows the first 500 characters of the synthesis report or summary,
 * with an expand button to reveal full content.
 */
import { useState } from 'react';

interface ExecutiveSummaryProps {
  report: Record<string, unknown> | null;
}

const PREVIEW_LENGTH = 500;

function extractSummary(report: Record<string, unknown>): string | null {
  const candidates: unknown[] = [
    report?.synthesis_report,
    report?.executive_summary,
    report?.summary,
    (report?.metadata as Record<string, unknown>)?.summary,
  ];

  for (const candidate of candidates) {
    if (typeof candidate === 'string' && candidate.trim().length > 0) {
      return candidate.trim();
    }
  }

  return null;
}

export function ExecutiveSummary({ report }: ExecutiveSummaryProps) {
  const [expanded, setExpanded] = useState(false);

  if (!report) {
    return null;
  }

  const fullText = extractSummary(report);
  if (!fullText) {
    return null;
  }

  const needsTruncation = fullText.length > PREVIEW_LENGTH;
  const displayText = expanded || !needsTruncation
    ? fullText
    : `${fullText.slice(0, PREVIEW_LENGTH)}...`;

  return (
    <div className="bg-fin-card border border-fin-border rounded-lg p-4">
      <h4 className="text-sm font-semibold text-fin-text mb-2">摘要总结</h4>
      <p className="text-sm text-fin-text-secondary leading-relaxed whitespace-pre-wrap">
        {displayText}
      </p>
      {needsTruncation ? (
        <button
          type="button"
          onClick={() => setExpanded((prev) => !prev)}
          className="mt-2 text-xs text-fin-primary hover:underline"
        >
          {expanded ? '收起' : '展开全文'}
        </button>
      ) : null}
    </div>
  );
}

export default ExecutiveSummary;
