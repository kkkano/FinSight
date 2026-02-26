/**
 * ResearchTab - 深度研究面板
 *
 * 关键增强：
 * 1) 串票硬拦截：report.ticker 与 activeTicker 不一致时，红条告警并禁用结论区。
 * 2) 三态占位：无数据 / 执行中 / 证据不足。
 * 3) 新鲜度标签：价格时间戳、财报期、新闻窗口。
 * 4) 证据不足条目支持一键展开到引用片段（非“问这条”对话链路）。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

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

type FreshnessTone = 'default' | 'warning';

interface FreshnessBadge {
  key: string;
  label: string;
  value: string;
  tone: FreshnessTone;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function asStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => asString(item)).filter(Boolean);
}

function formatQualityBlockedHint(reasonCodes: string[], reasonMessages: string[]): string {
  const uniqueMessages = Array.from(new Set(reasonMessages.map((item) => item.trim()).filter(Boolean)));
  if (uniqueMessages.length > 0) {
    return `报告被质量门禁拦截，未发布。原因：${uniqueMessages.slice(0, 3).join('；')}`;
  }
  const uniqueCodes = Array.from(new Set(reasonCodes.map((item) => item.trim()).filter(Boolean)));
  if (uniqueCodes.length > 0) {
    return `报告被质量门禁拦截，未发布。原因代码：${uniqueCodes.join(', ')}`;
  }
  return '报告被质量门禁拦截，未发布。请补充证据后重试。';
}

function normalizeGroundingRate(value: unknown): number | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return null;
  }
  return Math.max(0, Math.min(1, value));
}

function parseIsoMillis(value: string): number | null {
  if (!value) return null;
  const millis = Date.parse(value);
  return Number.isFinite(millis) ? millis : null;
}

function formatUtcTimestamp(value: string): string {
  const millis = parseIsoMillis(value);
  if (millis == null) return '--';
  const date = new Date(millis);
  const month = String(date.getUTCMonth() + 1).padStart(2, '0');
  const day = String(date.getUTCDate()).padStart(2, '0');
  const hour = String(date.getUTCHours()).padStart(2, '0');
  const minute = String(date.getUTCMinutes()).padStart(2, '0');
  return `${month}-${day} ${hour}:${minute} UTC`;
}

function formatAgeLabel(hours: number): string {
  if (!Number.isFinite(hours) || hours < 0) return '--';
  if (hours < 1) return '<1h';
  if (hours < 24) return `${Math.round(hours)}h`;
  return `${Math.round(hours / 24)}d`;
}

function normalizeTickerToken(value: string): string {
  return value.trim().toUpperCase().replace(/[^A-Z0-9.\-_]/g, '');
}

function isTickerEquivalent(left: string, right: string): boolean {
  const l = normalizeTickerToken(left);
  const r = normalizeTickerToken(right);
  if (!l || !r) return false;
  if (l === r) return true;

  const aliasGroups = [
    ['GOOG', 'GOOGL'],
    ['BRK.B', 'BRK-B'],
    ['BRKB', 'BRK-B', 'BRK.B'],
  ];

  return aliasGroups.some((group) => group.includes(l) && group.includes(r));
}

function isReportTickerAligned(activeTicker: string, reportTickerLabel: string): boolean {
  const active = normalizeTickerToken(activeTicker);
  if (!active) return true;

  const reportLabel = normalizeTickerToken(reportTickerLabel);
  if (!reportLabel) return true;
  if (isTickerEquivalent(active, reportLabel)) return true;

  const tokens = reportTickerLabel
    .toUpperCase()
    .split(/[^A-Z0-9.\-_]+/)
    .map((token) => normalizeTickerToken(token))
    .filter(Boolean);

  return tokens.some((token) => isTickerEquivalent(active, token));
}

function resolveFocusHintFromRequirement(requirement: string): string | null {
  const lower = requirement.toLowerCase();
  if (lower.includes('10-k')) return '10-k annual report sec';
  if (lower.includes('10-q')) return '10-q quarterly report sec';
  if (lower.includes('电话会') || lower.includes('纪要') || lower.includes('transcript') || lower.includes('earnings')) {
    return 'earnings transcript conference call';
  }
  if (
    lower.includes('reuters')
    || lower.includes('bloomberg')
    || lower.includes('wsj')
    || lower.includes('ft')
    || lower.includes('cnbc')
    || lower.includes('yahoo')
  ) {
    return 'reuters bloomberg wsj ft cnbc yahoo';
  }
  if (lower.includes('摘录') || lower.includes('snippet')) return 'snippet quote excerpt';
  const chineseTokens = lower.match(/[\u4e00-\u9fff]{2,}/g);
  if (chineseTokens && chineseTokens.length > 0) {
    return chineseTokens.slice(0, 3).join(' ');
  }
  return requirement.slice(0, 20).trim() || null;
}

function extractPriceAsOf(reportMeta: Record<string, unknown> | null): string {
  const agentSummaries = Array.isArray(reportMeta?.agent_summaries)
    ? reportMeta?.agent_summaries
    : [];

  for (const item of agentSummaries) {
    const summary = asRecord(item);
    if (!summary) continue;
    const agentName = asString(summary.agent_name);
    if (agentName !== 'price_agent') continue;

    const rawOutput = asRecord(summary.raw_output);
    const asOf = asString(rawOutput?.as_of) || asString(rawOutput?.timestamp) || asString(summary.as_of);
    if (asOf) return asOf;
  }

  return '';
}

function extractFilingPeriodLabel(
  reportRecord: Record<string, unknown> | null,
  qualityHints: Record<string, unknown> | null,
): string {
  const synthesisReport = asString(reportRecord?.synthesis_report);
  const quarterMatch = synthesisReport.match(/\b(20\d{2}\s*Q[1-4])\b/i);
  if (quarterMatch?.[1]) return quarterMatch[1].replace(/\s+/g, '').toUpperCase();

  const qualityStats = asRecord(qualityHints?.stats);
  const has10k = qualityStats?.has_10k === true;
  const has10q = qualityStats?.has_10q === true;
  if (has10k && has10q) return '10-K + 10-Q';
  if (has10k) return '10-K';
  if (has10q) return '10-Q';

  const secCountRaw = Number(qualityStats?.sec_filing_count);
  if (Number.isFinite(secCountRaw) && secCountRaw > 0) {
    return `SEC ${Math.round(secCountRaw)}条`;
  }
  return '--';
}

function buildFreshnessBadges(
  reportRecord: Record<string, unknown> | null,
  reportMeta: Record<string, unknown> | null,
  qualityHints: Record<string, unknown> | null,
  citations: Record<string, unknown>[],
): FreshnessBadge[] {
  const now = Date.now();

  const priceAsOf = extractPriceAsOf(reportMeta) || asString(reportRecord?.generated_at);
  const priceMillis = parseIsoMillis(priceAsOf);
  const priceAgeHours = priceMillis != null ? (now - priceMillis) / 3600000 : Number.NaN;
  const priceBadge: FreshnessBadge = {
    key: 'price_as_of',
    label: '价格时间戳',
    value: priceAsOf ? `${formatUtcTimestamp(priceAsOf)} (${formatAgeLabel(priceAgeHours)}前)` : '--',
    tone: Number.isFinite(priceAgeHours) && priceAgeHours > 24 ? 'warning' : 'default',
  };

  const filingLabel = extractFilingPeriodLabel(reportRecord, qualityHints);
  const filingBadge: FreshnessBadge = {
    key: 'filing_period',
    label: '财报期',
    value: filingLabel,
    tone: filingLabel === '--' ? 'warning' : 'default',
  };

  const publishedMillis = citations
    .map((citation) => parseIsoMillis(asString(asRecord(citation)?.published_date)))
    .filter((value): value is number => value != null)
    .sort((a, b) => a - b);

  let newsValue = '--';
  let newsTone: FreshnessTone = 'warning';
  if (publishedMillis.length > 0) {
    const oldest = publishedMillis[0];
    const newest = publishedMillis[publishedMillis.length - 1];
    const newestAgeHours = (now - newest) / 3600000;
    const spanHours = Math.max(0, (newest - oldest) / 3600000);
    const spanLabel = spanHours < 24 ? `${Math.max(1, Math.round(spanHours))}h` : `${Math.round(spanHours / 24)}d`;
    newsValue = `最新 ${formatAgeLabel(newestAgeHours)} · 窗口 ${spanLabel}`;
    newsTone = newestAgeHours > 72 ? 'warning' : 'default';
  }

  const newsBadge: FreshnessBadge = {
    key: 'news_window',
    label: '新闻窗口',
    value: newsValue,
    tone: newsTone,
  };

  return [priceBadge, filingBadge, newsBadge];
}

function renderFreshnessBadge(badge: FreshnessBadge) {
  const className = badge.tone === 'warning'
    ? 'border-yellow-400/40 bg-yellow-500/10 text-yellow-100'
    : 'border-fin-border/80 bg-fin-card text-fin-text';

  return (
    <div
      key={badge.key}
      className={`rounded-lg border px-3 py-2 text-xs ${className}`}
      data-testid={`research-freshness-${badge.key}`}
    >
      <div className="text-2xs opacity-80">{badge.label}</div>
      <div className="mt-0.5 font-medium">{badge.value}</div>
    </div>
  );
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

  const insightsData = useDashboardStore((s) => s.insightsData);
  const insightsLoading = useDashboardStore((s) => s.insightsLoading);
  const insightsError = useDashboardStore((s) => s.insightsError);
  const insightsStale = useDashboardStore((s) => s.insightsStale);
  useDashboardInsights(ticker);

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
  const [referenceFocusHint, setReferenceFocusHint] = useState<string | null>(null);
  const [referenceFocusToken, setReferenceFocusToken] = useState(0);

  useEffect(() => {
    setReferenceFocusHint(null);
    setReferenceFocusToken(0);
  }, [ticker]);

  const recentRuns = useExecutionStore((s) => s.recentRuns);
  const latestDashboardOutcome = useMemo(() => {
    const upperTicker = ticker?.toUpperCase();
    if (!upperTicker) return null;
    for (const run of recentRuns) {
      if (
        run.status === 'done'
        && run.source?.startsWith('dashboard')
        && run.outputMode === 'investment_report'
        && run.tickers?.some((item) => item.toUpperCase() === upperTicker)
      ) {
        return {
          runId: run.runId,
          completedAt: run.completedAt,
          qualityBlocked: run.qualityBlocked === true,
          blockedReasonCodes: run.blockedReasonCodes ?? [],
          qualityReasonMessages: (run.qualityReasons ?? [])
            .map((item) => item.message)
            .filter(Boolean),
        };
      }
    }
    return null;
  }, [recentRuns, ticker]);
  const lastSyncedCompletionRef = useRef<string | null>(null);

  const pollReportAfterComplete = useCallback(async () => {
    setSyncingReport(true);
    setSyncHint('报告已生成，正在同步索引…');

    for (let i = 0; i < REPORT_SYNC_MAX_RETRIES; i += 1) {
      const latest = await refetch();
      if (latest) {
        setSyncingReport(false);
        setSyncHint(null);
        return;
      }
      if (i < REPORT_SYNC_MAX_RETRIES - 1) {
        setSyncHint(`报告已生成，等待索引同步（${i + 1}/${REPORT_SYNC_MAX_RETRIES}）…`);
        await sleep(REPORT_SYNC_RETRY_DELAY_MS);
      }
    }

    setSyncingReport(false);
    setSyncHint('报告已生成但索引尚未完成，请稍后重试或刷新页面。');
  }, [refetch]);

  const { execute, isRunning, currentStep, error } = useExecuteAgent({
    onError: () => {
      setSyncingReport(false);
      setSyncHint(null);
    },
  });

  useEffect(() => {
    if (!latestDashboardOutcome || !ticker || syncingReport || isRunning) return;

    const completionKey = `${latestDashboardOutcome.runId}:${latestDashboardOutcome.completedAt ?? ''}`;
    if (completionKey === lastSyncedCompletionRef.current) return;
    lastSyncedCompletionRef.current = completionKey;

    if (latestDashboardOutcome.qualityBlocked) {
      setSyncingReport(false);
      setSyncHint(
        formatQualityBlockedHint(
          latestDashboardOutcome.blockedReasonCodes,
          latestDashboardOutcome.qualityReasonMessages,
        ),
      );
      return;
    }

    void pollReportAfterComplete();
  }, [latestDashboardOutcome, ticker, syncingReport, isRunning, pollReportAfterComplete]);

  const handleDeepAnalysis = () => {
    if (!ticker || isRunning || syncingReport) return;

    lastSyncedCompletionRef.current = null;
    const includeDeepSearch = deepAnalysisIncludeDeepSearch;
    setSyncHint(
      includeDeepSearch
        ? '已提交任务，正在执行 deep_search 并回填研究卡片…'
        : '已提交任务，正在生成深度报告并回填研究卡片…',
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

  const handleFocusRequirement = useCallback((requirement: string) => {
    const focusHint = resolveFocusHintFromRequirement(requirement);
    setReferenceFocusHint(focusHint);
    setReferenceFocusToken((prev) => prev + 1);

    requestAnimationFrame(() => {
      const anchor = document.getElementById('research-reference-list');
      if (anchor) {
        anchor.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    });
  }, []);

  if (loading) {
    return (
      <div className="space-y-4">
        <ResearchMetadata reportData={null} loading />
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
    const runningState = isRunning || syncingReport;
    const blockedState = !runningState && Boolean(syncHint?.startsWith('报告被质量门禁拦截'));

    return (
      <div className="space-y-4">
        <ResearchMetadata reportData={null} />

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

        <div
          className="rounded-xl border border-fin-border bg-fin-card px-4 py-4"
          data-testid="research-empty-state"
          data-state={runningState ? 'running' : blockedState ? 'blocked' : 'empty'}
        >
          <div className="text-sm font-medium text-fin-text">
            {runningState
              ? '深度分析执行中'
              : blockedState
                ? '报告未发布（质量门禁拦截）'
                : '暂无深度分析数据'}
          </div>
          <div className="mt-1 text-xs text-fin-muted">
            {runningState
              ? (currentStep || syncHint || '任务执行中，结果会自动回填。')
              : (syncHint || '尚未生成完整研究报告，请先执行一次深度分析。')}
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={handleDeepAnalysis}
              disabled={!ticker || runningState}
              className="px-3 py-1.5 rounded-lg border border-fin-primary/40 bg-fin-primary/10 text-fin-primary hover:bg-fin-primary/20 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {runningState ? '执行中…' : '生成深度报告'}
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
          </div>

          {error && (
            <div className="mt-2 text-xs text-fin-danger">
              生成失败：{error}
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
  const qualityMissing = asStringList(qualityHints?.missing_requirements);
  const freshnessBadges = buildFreshnessBadges(
    reportRecord,
    reportMeta,
    qualityHints,
    reportData.citations || [],
  );

  const groundingRate =
    normalizeGroundingRate(reportRecord?.grounding_rate) ??
    normalizeGroundingRate(asRecord(reportMeta?.grounding)?.grounding_rate) ??
    normalizeGroundingRate(asRecord(reportHints?.grounding)?.grounding_rate) ??
    normalizeGroundingRate(asRecord(qualityHints?.grounding)?.grounding_rate);

  const showLowGroundingBanner = groundingRate !== null && groundingRate < 0.6;
  const groundingRateText = groundingRate !== null ? `${Math.round(groundingRate * 100)}%` : '--';

  const activeTicker = asString(ticker).toUpperCase();
  const reportTicker = asString(reportRecord?.ticker).toUpperCase();
  const hasTickerMismatch = Boolean(
    activeTicker
    && reportTicker
    && !isReportTickerAligned(activeTicker, reportTicker),
  );

  if (hasTickerMismatch) {
    return (
      <div className="space-y-4">
        <ResearchMetadata reportData={reportData} />

        <div className="grid grid-cols-1 md:grid-cols-3 gap-2" data-testid="research-freshness-badges">
          {freshnessBadges.map(renderFreshnessBadge)}
        </div>

        <div
          className="rounded-xl border border-fin-danger/50 bg-fin-danger/10 px-4 py-3"
          data-testid="research-ticker-mismatch"
        >
          <div className="text-sm font-semibold text-fin-danger">
            ⚠ 报告标的不匹配，结论区已禁用
          </div>
          <div className="mt-1 text-xs text-fin-text/90">
            当前标的：{activeTicker || '--'}；报告标的：{reportTicker || '--'}。为避免串票误导，已阻断结论展示。
          </div>
          <button
            type="button"
            onClick={handleDeepAnalysis}
            disabled={!ticker || isRunning || syncingReport}
            className="mt-3 px-3 py-1.5 rounded-lg border border-fin-danger/40 bg-fin-danger/15 text-fin-danger hover:bg-fin-danger/20 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            重新生成当前标的报告
          </button>
        </div>

        <div
          className="rounded-xl border border-fin-border bg-fin-card/60 px-4 py-6 text-sm text-fin-muted"
          data-testid="research-conclusion-disabled"
        >
          结论区已禁用：请先修复串票后再查看“综合评估 / 完整研究报告”。
        </div>

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

  return (
    <div className="space-y-4">
      <ResearchMetadata reportData={reportData} />

      <div className="grid grid-cols-1 md:grid-cols-3 gap-2" data-testid="research-freshness-badges">
        {freshnessBadges.map(renderFreshnessBadge)}
      </div>

      {showLowGroundingBanner && (
        <div
          className="rounded-xl border border-yellow-400/40 bg-yellow-500/10 px-4 py-3 text-sm text-yellow-100"
          data-testid="research-grounding-warning"
        >
          <div className="font-medium">⚠ 证据溯源率偏低（{groundingRateText}）</div>
          <div className="mt-1 text-xs text-yellow-100/85">
            当前结论中存在较多缺少直接证据锚点的断言，建议优先核对引用列表与原文摘要后再决策。
          </div>
        </div>
      )}

      {qualityMissing.length > 0 && (
        <div
          className="rounded-xl border border-fin-warning/40 bg-fin-warning/10 px-4 py-3"
          data-testid="research-empty-state"
          data-state="quality-gap"
        >
          <div className="text-sm font-semibold text-fin-warning">证据不足（质量门槛未满足）</div>
          <div className="mt-1 text-xs text-fin-text/80">
            已检测到关键证据缺口。你可以直接展开对应引用片段核对，不需要走“问这条”对话链路。
          </div>
          <div className="mt-2 space-y-2">
            {qualityMissing.slice(0, 6).map((item, idx) => (
              <div key={`${idx}-${item}`} className="flex items-start gap-2 text-xs">
                <span className="text-fin-warning mt-0.5">•</span>
                <span className="flex-1 text-fin-text/85">{item}</span>
                <button
                  type="button"
                  className="shrink-0 px-2 py-0.5 rounded border border-fin-border text-fin-primary hover:bg-fin-primary/10 transition-colors"
                  onClick={() => handleFocusRequirement(item)}
                >
                  查看引用片段
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

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

      <div className="bg-fin-card rounded-xl border border-fin-border overflow-hidden">
        <button
          type="button"
          onClick={() => setReportExpanded((prev) => !prev)}
          className="w-full flex items-center justify-between px-4 py-3 text-sm font-medium text-fin-text hover:bg-fin-border/10 transition-colors"
        >
          <span className="flex items-center gap-2">
            <span>📚</span>
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

      <ReferenceList
        citations={reportData.citations}
        focusHint={referenceFocusHint}
        focusToken={referenceFocusToken}
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

export default ResearchTab;
