/**
 * ResearchTab - TradingKey 风格结构化洞察面板
 *
 * 布局（从上到下）：
 *   1. ResearchMetadata    — 报告元数据（来源、时间）
 *   2. ResearchOverviewBar — 综合评估大横条
 *   3. ResearchInsightGrid — 4 张洞察卡片（财务/技术/新闻/行业）
 *   4. 可折叠完整报告（ExecutiveSummary + CoreFindings + ConflictPanel）
 *   5. ReferenceList       — 引用列表
 *
 * 数据来源二合一：
 *   - useDashboardInsights   → InsightCard 评分卡
 *   - useLatestReport        → 完整报告文本
 */
import { useCallback, useEffect, useRef, useState } from 'react';

import { useDashboardStore } from '../../../store/dashboardStore.ts';
import { useExecutionStore } from '../../../store/executionStore.ts';
import { useLatestReport } from '../../../hooks/useLatestReport.ts';
import { useDashboardInsights } from '../../../hooks/useDashboardInsights.ts';
import { useExecuteAgent } from '../../../hooks/useExecuteAgent.ts';
import type { InsightCard } from '../../../types/dashboard.ts';
import { asRecord } from '../../../utils/record.ts';
import { ResearchMetadata } from './research/ResearchMetadata.tsx';
import { ResearchOverviewBar } from './research/ResearchOverviewBar.tsx';
import { ResearchInsightGrid } from './research/ResearchInsightGrid.tsx';
import { ExecutiveSummary } from './research/ExecutiveSummary.tsx';
import { CoreFindings } from './research/CoreFindings.tsx';
import { ConflictPanel } from './research/ConflictPanel.tsx';
import { ReferenceList } from './research/ReferenceList.tsx';
import { ScoreExplainDrawer } from './research/ScoreExplainDrawer.tsx';

const REPORT_SYNC_MAX_RETRIES = 12;
const REPORT_SYNC_RETRY_DELAY_MS = 1000;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

function normalizeGroundingRate(value: unknown): number | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return null;
  }

  return Math.max(0, Math.min(1, value));
}

export function ResearchTab() {
  const activeAsset = useDashboardStore((s) => s.activeAsset);
  const deepAnalysisIncludeDeepSearch = useDashboardStore((s) => s.deepAnalysisIncludeDeepSearch);
  const setDeepAnalysisIncludeDeepSearch = useDashboardStore((s) => s.setDeepAnalysisIncludeDeepSearch);
  const ticker = activeAsset?.symbol ?? null;
  const { data: reportData, loading, refetch } = useLatestReport(ticker, {
    sourceType: 'dashboard',
    fallbackToAnySource: false,
    preferredSourceTrigger: 'dashboard_deep_search',
  });

  // ==================== AI Insights 数据 ====================
  const insightsData = useDashboardStore((s) => s.insightsData);
  const insightsLoading = useDashboardStore((s) => s.insightsLoading);
  const insightsError = useDashboardStore((s) => s.insightsError);
  const insightsStale = useDashboardStore((s) => s.insightsStale);
  useDashboardInsights(ticker);

  // ==================== 完整报告折叠状态 ====================
  const [reportExpanded, setReportExpanded] = useState(true);
  const [scoreDrawerState, setScoreDrawerState] = useState<{
    open: boolean;
    title: string;
    insight: InsightCard | null;
  }>({
    open: false,
    title: '',
    insight: null,
  });

  const [syncingReport, setSyncingReport] = useState(false);
  const [syncHint, setSyncHint] = useState<string | null>(null);

  // ==================== 跨实例执行完成感知 ====================
  // 检测 executionStore 中任何 dashboard 来源、匹配当前 ticker 的已完成执行
  // 解决: StockHeader 触发执行 → ResearchTab 无法感知完成的问题
  const latestDashboardCompletion = useExecutionStore((s) => {
    const upperTicker = ticker?.toUpperCase();
    if (!upperTicker) return null;
    for (const r of s.recentRuns) {
      if (
        r.status === 'done' &&
        r.source?.startsWith('dashboard') &&
        r.outputMode === 'investment_report' &&
        r.tickers?.some((t) => t.toUpperCase() === upperTicker)
      ) {
        return r.completedAt;
      }
    }
    return null;
  });
  const lastSyncedCompletionRef = useRef<string | null>(null);

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

  // ==================== 外部执行完成 → 自动拉取报告 ====================
  // 当 StockHeader 或其他来源触发的 dashboard 执行完成时，自动 poll 报告索引
  useEffect(() => {
    if (
      latestDashboardCompletion &&
      latestDashboardCompletion !== lastSyncedCompletionRef.current &&
      ticker &&
      !syncingReport &&
      !isRunning
    ) {
      lastSyncedCompletionRef.current = latestDashboardCompletion;
      void pollReportAfterComplete();
    }
  }, [latestDashboardCompletion, ticker, syncingReport, isRunning, pollReportAfterComplete]);

  const handleDeepAnalysis = () => {
    if (!ticker || isRunning || syncingReport) return;

    // 当通过 ResearchTab 自身按钮发起时，重置外部完成追踪标记
    // 防止 pollReportAfterComplete 被触发两次（自身 onComplete + 外部感知）
    lastSyncedCompletionRef.current = null;

    const includeDeepSearch = deepAnalysisIncludeDeepSearch;
    setSyncHint(
      includeDeepSearch
        ? '已提交任务，正在执行深度搜索并回填研究卡片...'
        : '已提交任务，正在生成深度报告并回填研究卡片...',
    );
    execute({
      query: includeDeepSearch
        ? `对 ${ticker} 做深度搜索，输出可追溯证据与关键结论`
        : `生成 ${ticker} 投资报告`,
      tickers: [ticker],
      outputMode: 'investment_report',
      analysisDepth: includeDeepSearch ? 'deep_research' : 'report',
      source: includeDeepSearch ? 'dashboard_deep_search' : 'dashboard_header',
    });
  };

  const handleOpenScoreExplain = (insight: InsightCard, title: string) => {
    setScoreDrawerState({
      open: true,
      title,
      insight,
    });
  };

  const handleCloseScoreExplain = () => {
    setScoreDrawerState((prev) => ({ ...prev, open: false }));
  };

  if (loading) {
    return (
      <div className="space-y-4">
        <ResearchMetadata reportData={null} loading />
        {/* 加载时也展示 insights 数据（可能已有缓存） */}
        <ResearchOverviewBar
          overview={insightsData?.overview}
          loading={insightsLoading}
          onOpenScoreExplain={handleOpenScoreExplain}
        />
        <ResearchInsightGrid
          insights={insightsData}
          loading={insightsLoading}
          error={insightsError}
          stale={insightsStale}
          onOpenScoreExplain={handleOpenScoreExplain}
        />
        <ScoreExplainDrawer
          open={scoreDrawerState.open}
          title={scoreDrawerState.title}
          insight={scoreDrawerState.insight}
          onClose={handleCloseScoreExplain}
        />
      </div>
    );
  }

  if (!reportData) {
    return (
      <div className="space-y-4">
        <ResearchMetadata reportData={null} />

        {/* 即使没有报告，也展示 AI 洞察卡片 */}
        <ResearchOverviewBar
          overview={insightsData?.overview}
          loading={insightsLoading}
          onOpenScoreExplain={handleOpenScoreExplain}
        />
        <ResearchInsightGrid
          insights={insightsData}
          loading={insightsLoading}
          error={insightsError}
          stale={insightsStale}
          onOpenScoreExplain={handleOpenScoreExplain}
        />

        {/* 深度分析触发区 */}
        <div className="flex flex-col items-center justify-center py-8 text-fin-muted text-sm gap-3">
          <div>尚未生成完整研究报告</div>
          <button
            type="button"
            onClick={handleDeepAnalysis}
            disabled={!ticker || isRunning || syncingReport}
            className="px-3 py-1.5 rounded-lg border border-fin-primary/40 bg-fin-primary/10 text-fin-primary hover:bg-fin-primary/20 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isRunning || syncingReport ? '执行中...' : '生成深度报告'}
          </button>
          <label className="flex items-center gap-1.5 px-2 py-1 text-2xs text-fin-muted border border-fin-border rounded-lg">
            <input
              type="checkbox"
              className="accent-fin-primary"
              checked={deepAnalysisIncludeDeepSearch}
              onChange={(event) => setDeepAnalysisIncludeDeepSearch(event.target.checked)}
            />
            含 deepsearch
          </label>
          <div className="text-2xs text-fin-muted text-center max-w-[32rem]">
            深度分析统一走 report 模式；勾选“含 deepsearch”会强制加入 deep_search_agent。
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
        <ScoreExplainDrawer
          open={scoreDrawerState.open}
          title={scoreDrawerState.title}
          insight={scoreDrawerState.insight}
          onClose={handleCloseScoreExplain}
        />
      </div>
    );
  }

  const report = reportData.report;
  const reportRecord = asRecord(report);
  const reportMeta = asRecord(reportRecord?.meta);
  const reportHints = asRecord(reportRecord?.report_hints);
  const qualityHints = asRecord(reportHints?.quality);

  const groundingRate =
    normalizeGroundingRate(reportRecord?.grounding_rate) ??
    normalizeGroundingRate(asRecord(reportMeta?.grounding)?.grounding_rate) ??
    normalizeGroundingRate(asRecord(reportHints?.grounding)?.grounding_rate) ??
    normalizeGroundingRate(asRecord(qualityHints?.grounding)?.grounding_rate);

  const showLowGroundingBanner = groundingRate !== null && groundingRate < 0.6;
  const groundingRateText = groundingRate !== null ? `${Math.round(groundingRate * 100)}%` : '--';

  return (
    <div className="space-y-4">
      {/* 元数据 */}
      <ResearchMetadata reportData={reportData} />

      {showLowGroundingBanner && (
        <div className="rounded-xl border border-yellow-400/40 bg-yellow-500/10 px-4 py-3 text-sm text-yellow-100">
          <div className="font-medium">⚠ 证据溯源率偏低（{groundingRateText}）</div>
          <div className="mt-1 text-xs text-yellow-100/85">
            当前结论中存在较多缺少直接证据锚点的断言，建议优先核对引用列表与原文摘要后再决策。
          </div>
        </div>
      )}

      {/* AI 综合评估横条 */}
      <ResearchOverviewBar
        overview={insightsData?.overview}
        loading={insightsLoading}
        onOpenScoreExplain={handleOpenScoreExplain}
      />

      {/* AI 洞察卡片网格：财务 / 技术 / 新闻 / 行业 */}
      <ResearchInsightGrid
        insights={insightsData}
        loading={insightsLoading}
        error={insightsError}
        stale={insightsStale}
        onOpenScoreExplain={handleOpenScoreExplain}
      />

      {/* 可折叠完整报告 */}
      <div className="bg-fin-card rounded-xl border border-fin-border overflow-hidden">
        <button
          type="button"
          onClick={() => setReportExpanded((prev) => !prev)}
          className="w-full flex items-center justify-between px-4 py-3 text-sm font-medium text-fin-text hover:bg-fin-border/10 transition-colors"
        >
          <span className="flex items-center gap-2">
            <span>📄</span>
            完整研究报告
          </span>
          <span
            className={`text-fin-muted transition-transform duration-200 ${
              reportExpanded ? 'rotate-180' : ''
            }`}
          >
            ▼
          </span>
        </button>

        {reportExpanded && (
          <div className="border-t border-fin-border px-4 py-4 space-y-4">
            <ExecutiveSummary report={report} />
            <CoreFindings report={report} />
            <ConflictPanel report={report} />
          </div>
        )}
      </div>

      {/* 引用列表 */}
      <ReferenceList citations={reportData.citations} />

      <ScoreExplainDrawer
        open={scoreDrawerState.open}
        title={scoreDrawerState.title}
        insight={scoreDrawerState.insight}
        onClose={handleCloseScoreExplain}
      />
    </div>
  );
}

export default ResearchTab;
