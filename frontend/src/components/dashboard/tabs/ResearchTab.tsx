/**
 * ResearchTab - Container component for the Research tab panel.
 *
 * Combines ResearchMetadata, ExecutiveSummary, CoreFindings,
 * ConflictPanel, and ReferenceList from the latest report.
 */
import { useCallback, useState } from 'react';

import { useDashboardStore } from '../../../store/dashboardStore.ts';
import { useLatestReport } from '../../../hooks/useLatestReport.ts';
import { useExecuteAgent } from '../../../hooks/useExecuteAgent.ts';
import { ResearchMetadata } from './research/ResearchMetadata.tsx';
import { ExecutiveSummary } from './research/ExecutiveSummary.tsx';
import { CoreFindings } from './research/CoreFindings.tsx';
import { ConflictPanel } from './research/ConflictPanel.tsx';
import { ReferenceList } from './research/ReferenceList.tsx';

const REPORT_SYNC_MAX_RETRIES = 5;
const REPORT_SYNC_RETRY_DELAY_MS = 800;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

export function ResearchTab() {
  const activeAsset = useDashboardStore((s) => s.activeAsset);
  const ticker = activeAsset?.symbol ?? null;
  const { data: reportData, loading, refetch } = useLatestReport(ticker, {
    sourceType: 'dashboard',
    fallbackToAnySource: false,
  });
  const [syncingReport, setSyncingReport] = useState(false);
  const [syncHint, setSyncHint] = useState<string | null>(null);

  const pollReportAfterComplete = useCallback(async () => {
    setSyncingReport(true);
    setSyncHint('报告已生成，正在同步到索引...');

    for (let i = 0; i < REPORT_SYNC_MAX_RETRIES; i += 1) {
      const latest = await refetch();
      if (latest) {
        setSyncingReport(false);
        setSyncHint(null);
        return;
      }

      if (i < REPORT_SYNC_MAX_RETRIES - 1) {
        setSyncHint(`报告已生成，等待索引同步（${i + 1}/${REPORT_SYNC_MAX_RETRIES}）...`);
        await sleep(REPORT_SYNC_RETRY_DELAY_MS);
      }
    }

    setSyncingReport(false);
    setSyncHint('报告已生成但索引尚未完成，请稍后重试或刷新页面。');
  }, [refetch]);

  const { execute, isRunning, currentStep, error } = useExecuteAgent({
    onComplete: () => {
      void pollReportAfterComplete();
    },
    onError: () => {
      setSyncingReport(false);
      setSyncHint(null);
    },
  });

  const handleGenerateReport = () => {
    if (!ticker || isRunning || syncingReport) return;
    setSyncHint('已提交任务，正在执行深度搜索并回填研究卡片...');
    execute({
      query: `对 ${ticker} 做深度搜索，输出可追溯证据与关键结论`,
      tickers: [ticker],
      outputMode: 'investment_report',
      source: 'dashboard_deep_search',
    });
  };

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
        <div className="flex flex-col items-center justify-center h-48 text-fin-muted text-sm gap-3">
          <div>尚未生成研究报告</div>
          <button
            type="button"
            onClick={handleGenerateReport}
            disabled={!ticker || isRunning || syncingReport}
            className="px-3 py-1.5 rounded-lg border border-fin-primary/40 bg-fin-primary/10 text-fin-primary hover:bg-fin-primary/20 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isRunning || syncingReport ? '执行中...' : '深度搜索并填充'}
          </button>
          <div className="text-2xs text-fin-muted text-center max-w-[32rem]">
            深度搜索会优先补齐研究卡片，并附来源证据；不再把聊天报告直接复用到仪表盘。
          </div>

          {(isRunning || syncingReport) && (
            <div className="text-xs text-fin-muted">
              {currentStep || syncHint || '任务执行中...'}
            </div>
          )}

          {error && (
            <div className="text-xs text-red-400 max-w-[28rem] text-center">
              生成失败：{error}
            </div>
          )}

          {!error && syncHint && !isRunning && (
            <div className="text-xs text-fin-muted max-w-[28rem] text-center">
              {syncHint}
            </div>
          )}
        </div>
      </div>
    );
  }

  const report = reportData.report;

  return (
    <div className="space-y-4">
      <ResearchMetadata reportData={reportData} />
      <ExecutiveSummary report={report} />
      <CoreFindings report={report} />
      <ConflictPanel report={report} />
      <ReferenceList citations={reportData.citations} />
    </div>
  );
}

export default ResearchTab;
