/**
 * ResearchTab - Container component for the Research tab panel.
 *
 * Combines ResearchMetadata, ExecutiveSummary, CoreFindings,
 * ConflictPanel, and ReferenceList from the latest report.
 */
import { useDashboardStore } from '../../../store/dashboardStore.ts';
import { useLatestReport } from '../../../hooks/useLatestReport.ts';
import { ResearchMetadata } from './research/ResearchMetadata.tsx';
import { ExecutiveSummary } from './research/ExecutiveSummary.tsx';
import { CoreFindings } from './research/CoreFindings.tsx';
import { ConflictPanel } from './research/ConflictPanel.tsx';
import { ReferenceList } from './research/ReferenceList.tsx';

export function ResearchTab() {
  const activeAsset = useDashboardStore((s) => s.activeAsset);
  const ticker = activeAsset?.symbol ?? null;
  const { data: reportData, loading } = useLatestReport(ticker);

  if (loading) {
    return (
      <div className="space-y-4">
        <ResearchMetadata reportData={null} loading />
        <div className="bg-fin-card border border-fin-border rounded-lg p-4 animate-pulse">
          <div className="h-4 bg-fin-border rounded w-32 mb-3" />
          <div className="space-y-2">
            <div className="h-3 bg-fin-border rounded w-full" />
            <div className="h-3 bg-fin-border rounded w-5/6" />
            <div className="h-3 bg-fin-border rounded w-3/4" />
          </div>
        </div>
      </div>
    );
  }

  if (!reportData) {
    return (
      <div className="space-y-4">
        <ResearchMetadata reportData={null} />
        <div className="flex items-center justify-center h-48 text-fin-muted text-sm">
          执行分析以获取深度研究报告
        </div>
      </div>
    );
  }

  const report = reportData.report;

  return (
    <div className="space-y-4">
      {/* Quality metrics */}
      <ResearchMetadata reportData={reportData} />

      {/* Executive summary */}
      <ExecutiveSummary report={report} />

      {/* Core findings / sections */}
      <CoreFindings report={report} />

      {/* Conflict panel (only renders when conflicts exist) */}
      <ConflictPanel report={report} />

      {/* Reference / citation list */}
      <ReferenceList citations={reportData.citations} />
    </div>
  );
}

export default ResearchTab;
