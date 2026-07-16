import { Link } from 'react-router-dom';

import { buildHistoryReportHref } from '../../utils/reportLinkage';

type ReportArchiveLinkProps = {
  reportId: string;
};

export function ReportArchiveLink({ reportId }: ReportArchiveLinkProps) {
  if (!reportId.trim()) return null;

  return (
    <div className="mt-3 border-t border-fin-border/60 pt-3 text-xs text-fin-muted">
      <Link
        to={buildHistoryReportHref(reportId)}
        className="inline-flex min-h-11 items-center text-fin-primary transition-colors hover:text-fin-primary/80"
        data-testid={`chat-report-history-${reportId}`}
      >
        已归档 · 在历史中查看 →
      </Link>
    </div>
  );
}
