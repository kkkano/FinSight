import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { apiClient, type ReportIndexItem } from '../api/client';
import type { ReportIR } from '../types/index';
import { useStore } from '../store/useStore';
import { asRecord } from '../utils/record';
import { Card } from '../components/ui/Card';
import { PortfolioSummaryBar } from '../components/workbench/PortfolioSummaryBar';
import { PortfolioPieChart } from '../components/workbench/PortfolioPieChart';
import { QuickAnalysisBar } from '../components/workbench/QuickAnalysisBar';
import { RebalanceEntryCard } from '../components/workbench/RebalanceEntryCard';
import { ReportSection } from '../components/workbench/ReportSection';
import { TaskSection } from '../components/workbench/TaskSection';
import { ReportView } from '../components/report/ReportView';
import { usePortfolioSummary } from '../hooks/usePortfolioSummary';

type WorkbenchProps = {
  symbol: string;
  fromDashboard?: boolean;
  onNavigateToChat?: () => void;
};

interface VerifierClaim {
  claim: string;
  reason: string;
}

interface CitationSnippet {
  id: string;
  source: string;
  title: string;
  snippet: string;
  url?: string;
  publishedDate?: string;
}

interface WorkbenchQualityDrawerProps {
  open: boolean;
  onClose: () => void;
  qualityMissing: string[];
  verifierClaims: VerifierClaim[];
  citations: Record<string, unknown>[];
  initialFocusHint?: string | null;
}

// ==================== 数据解析工具 ====================

function asString(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function asStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => asString(item)).filter(Boolean);
}

function asVerifierClaims(value: unknown): VerifierClaim[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => asRecord(item))
    .filter((item): item is Record<string, unknown> => Boolean(item))
    .map((item) => ({
      claim: asString(item.claim).slice(0, 240),
      reason: asString(item.reason).slice(0, 240) || '证据池中未找到明确支撑',
    }))
    .filter((item) => Boolean(item.claim));
}

function normalizeGroundingRate(value: unknown): number | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return null;
  }
  return Math.max(0, Math.min(1, value));
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
  if (lower.includes('业绩电话会') || lower.includes('纪要') || lower.includes('transcript') || lower.includes('earnings')) {
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
  if (lower.includes('摘录') || lower.includes('snippet') || lower.includes('引用')) {
    return 'snippet quote excerpt';
  }
  return null;
}

function tokenizeFocusHint(hint: string | null | undefined): string[] {
  const normalized = asString(hint).toLowerCase();
  if (!normalized) return [];
  return normalized
    .split(/[\s,，/|]+/)
    .map((token) => token.trim())
    .filter((token) => token.length >= 2);
}

function domainFromUrl(url: string): string {
  try {
    const parsed = new URL(url);
    return parsed.hostname.replace(/^www\./i, '');
  } catch {
    return '';
  }
}

function resolveSourceLabel(citation: Record<string, unknown>): string {
  const source = asString(citation.source)
    || asString(citation.name)
    || asString(citation.publisher)
    || asString(citation.media)
    || asString(citation.outlet);
  if (source) return source;

  const title = asString(citation.title);
  if (title) {
    const titleAsDomain = domainFromUrl(title);
    return titleAsDomain || title;
  }

  const url = asString(citation.url);
  if (url) return domainFromUrl(url) || url;

  const sourceId = asString(citation.source_id);
  if (sourceId) return sourceId;

  return '未知来源';
}

function normalizeCitationSnippet(citation: Record<string, unknown>, index: number): CitationSnippet {
  const source = resolveSourceLabel(citation);
  const sourceId = asString(citation.source_id);
  const title = asString(citation.title) || source;
  const snippet = asString(citation.snippet)
    || asString(citation.quote)
    || asString(citation.summary)
    || asString(citation.text);
  const url = asString(citation.url) || undefined;
  const publishedDate = asString(citation.published_date) || undefined;

  return {
    id: sourceId || `citation-${index + 1}`,
    source,
    title,
    snippet: snippet || '[无正文摘录]',
    url,
    publishedDate,
  };
}

function snippetMatchesFocus(snippet: CitationSnippet, tokens: string[]): boolean {
  if (tokens.length === 0) return true;
  const haystack = [
    snippet.source,
    snippet.title,
    snippet.snippet,
    snippet.url || '',
  ]
    .join(' ')
    .toLowerCase();
  return tokens.some((token) => haystack.includes(token));
}

function formatPublishedDate(value?: string): string {
  if (!value) return '--';
  const millis = Date.parse(value);
  if (!Number.isFinite(millis)) return value;
  const date = new Date(millis);
  const month = String(date.getUTCMonth() + 1).padStart(2, '0');
  const day = String(date.getUTCDate()).padStart(2, '0');
  return `${month}-${day}`;
}

// ==================== 证据质量诊断抽屉 ====================

function WorkbenchQualityDrawer({
  open,
  onClose,
  qualityMissing,
  verifierClaims,
  citations,
  initialFocusHint,
}: WorkbenchQualityDrawerProps) {
  const [focusHint, setFocusHint] = useState<string | null>(initialFocusHint ?? null);

  useEffect(() => {
    if (!open) return;
    setFocusHint(initialFocusHint ?? null);
  }, [open, initialFocusHint]);

  const snippets = useMemo(
    () => (citations || []).map((citation, idx) => normalizeCitationSnippet(citation, idx)),
    [citations],
  );
  const focusTokens = useMemo(() => tokenizeFocusHint(focusHint), [focusHint]);
  const focusedSnippets = useMemo(
    () => snippets.filter((item) => snippetMatchesFocus(item, focusTokens)),
    [snippets, focusTokens],
  );
  const snippetsToDisplay = useMemo(() => {
    if (focusTokens.length === 0) return snippets.slice(0, 10);
    return (focusedSnippets.length > 0 ? focusedSnippets : snippets).slice(0, 10);
  }, [focusTokens, focusedSnippets, snippets]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/45" role="dialog" aria-modal="true">
      <div className="w-full max-w-lg h-full bg-fin-card border-l border-fin-border shadow-2xl overflow-y-auto" data-testid="workbench-quality-drawer">
        <div className="sticky top-0 z-10 px-4 py-3 border-b border-fin-border bg-fin-card/95 backdrop-blur">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold text-fin-text">证据质量诊断</h3>
              <p className="text-2xs text-fin-muted mt-0.5">不走“问这条”链路，直接定位证据片段。</p>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="text-xs text-fin-muted hover:text-fin-text transition-colors"
            >
              关闭
            </button>
          </div>
        </div>

        <div className="p-4 space-y-4">
          {qualityMissing.length > 0 && (
            <section className="rounded-lg border border-fin-warning/40 bg-fin-warning/10 p-3">
              <div className="text-xs font-semibold text-fin-warning">质量门槛缺口</div>
              <div className="mt-2 space-y-2">
                {qualityMissing.map((item, idx) => (
                  <div key={`${idx}-${item}`} className="text-xs text-fin-text/85">
                    <div className="flex items-start gap-2">
                      <span className="text-fin-warning mt-0.5">•</span>
                      <span className="flex-1">{item}</span>
                      <button
                        type="button"
                        className="shrink-0 px-2 py-0.5 rounded border border-fin-border text-fin-primary hover:bg-fin-primary/10 transition-colors"
                        onClick={() => setFocusHint(resolveFocusHintFromRequirement(item))}
                      >
                        定位片段
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}

          {verifierClaims.length > 0 && (
            <section className="rounded-lg border border-fin-danger/40 bg-fin-danger/10 p-3">
              <div className="text-xs font-semibold text-fin-danger">Verifier 核查缺口</div>
              <div className="mt-2 space-y-2">
                {verifierClaims.map((item, idx) => (
                  <div key={`${idx}-${item.claim}`} className="rounded border border-fin-danger/30 bg-fin-card/70 p-2 text-xs">
                    <div className="text-fin-text font-medium">{item.claim}</div>
                    <div className="mt-1 text-fin-text/75">{item.reason}</div>
                    <button
                      type="button"
                      className="mt-2 px-2 py-0.5 rounded border border-fin-border text-fin-primary hover:bg-fin-primary/10 transition-colors"
                      onClick={() => setFocusHint(item.claim)}
                    >
                      定位片段
                    </button>
                  </div>
                ))}
              </div>
            </section>
          )}

          <section className="rounded-lg border border-fin-border bg-fin-card/70" data-testid="workbench-quality-snippets">
            <div className="px-3 py-2 border-b border-fin-border/60 flex items-center justify-between">
              <span className="text-xs font-medium text-fin-text">引用片段</span>
              {focusTokens.length > 0 && (
                <span className="text-2xs text-fin-warning">
                  {focusedSnippets.length > 0
                    ? `已定位 ${focusedSnippets.length} 条相关证据`
                    : '未找到完全匹配，已展示最近证据'}
                </span>
              )}
            </div>
            <div className="divide-y divide-fin-border/60">
              {snippetsToDisplay.length === 0 && (
                <div className="px-3 py-4 text-xs text-fin-muted">暂无可展示引用片段。</div>
              )}
              {snippetsToDisplay.map((item) => {
                const focused = focusTokens.length > 0 && snippetMatchesFocus(item, focusTokens);
                return (
                  <div
                    key={item.id}
                    className={`px-3 py-2 ${focused ? 'bg-fin-warning/10' : ''}`}
                    data-testid="workbench-quality-snippet-item"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-xs text-fin-text truncate">{item.title}</div>
                      <span className="text-2xs text-fin-muted shrink-0">{formatPublishedDate(item.publishedDate)}</span>
                    </div>
                    <div className="mt-1 text-2xs text-fin-muted leading-relaxed">{item.snippet}</div>
                    <div className="mt-1 flex items-center justify-between gap-2">
                      <span className="text-2xs text-fin-muted truncate">{item.source}</span>
                      {item.url && (
                        <a
                          href={item.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-2xs text-fin-primary hover:underline shrink-0"
                        >
                          查看原文
                        </a>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        </div>
      </div>
      <button type="button" aria-label="close" className="flex-1 cursor-default" onClick={onClose} />
    </div>
  );
}

// ==================== 页面主体 ====================

export function Workbench({
  symbol,
  fromDashboard = false,
  onNavigateToChat,
}: WorkbenchProps) {
  const navigate = useNavigate();
  const { sessionId, portfolioPositions } = useStore();
  const portfolioSummary = usePortfolioSummary(sessionId);

  const [latestReports, setLatestReports] = useState<ReportIndexItem[]>([]);
  const [loadingReports, setLoadingReports] = useState(false);
  const [selectedReportId, setSelectedReportId] = useState<string | null>(null);
  const [selectedReport, setSelectedReport] = useState<ReportIR | null>(null);
  const [loadingSelectedReport, setLoadingSelectedReport] = useState(false);
  const [selectedReportError, setSelectedReportError] = useState<string | null>(null);
  const [qualityDrawerOpen, setQualityDrawerOpen] = useState(false);
  const [qualityFocusHint, setQualityFocusHint] = useState<string | null>(null);
  const replayRequestSeqRef = useRef(0);

  useEffect(() => {
    let cancelled = false;

    const run = async () => {
      setLoadingReports(true);
      try {
        const payload = await apiClient.listReportIndex({
          sessionId,
          limit: 12,
        });
        if (!cancelled) {
          setLatestReports(Array.isArray(payload.items) ? payload.items : []);
        }
      } catch {
        if (!cancelled) {
          setLatestReports([]);
        }
      } finally {
        if (!cancelled) {
          setLoadingReports(false);
        }
      }
    };

    run();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  useEffect(() => {
    if (latestReports.length === 0) {
      setSelectedReportId(null);
      setSelectedReport(null);
      return;
    }

    if (selectedReportId && latestReports.some((item) => item.report_id === selectedReportId)) {
      return;
    }

    const activeTicker = asString(symbol).toUpperCase();
    const preferred = latestReports.find((item) => asString(item.ticker).toUpperCase() === activeTicker) ?? latestReports[0];
    setSelectedReportId(preferred?.report_id ?? null);
  }, [latestReports, selectedReportId, symbol]);

  useEffect(() => {
    let cancelled = false;
    const requestSeq = ++replayRequestSeqRef.current;

    if (!selectedReportId) {
      setSelectedReport(null);
      setSelectedReportError(null);
      setLoadingSelectedReport(false);
      return () => {
        cancelled = true;
      };
    }

    const run = async () => {
      setLoadingSelectedReport(true);
      setSelectedReportError(null);

      try {
        const payload = await apiClient.getReportReplay({
          sessionId,
          reportId: selectedReportId,
        });
        if (cancelled || requestSeq !== replayRequestSeqRef.current) return;

        if (payload?.success && payload.report) {
          setSelectedReport(payload.report as ReportIR);
        } else {
          setSelectedReport(null);
          setSelectedReportError('报告加载失败，请稍后重试。');
        }
      } catch (error) {
        if (cancelled || requestSeq !== replayRequestSeqRef.current) return;
        setSelectedReport(null);
        setSelectedReportError(error instanceof Error ? error.message : '报告加载失败。');
      } finally {
        if (!cancelled && requestSeq === replayRequestSeqRef.current) {
          setLoadingSelectedReport(false);
        }
      }
    };

    void run();

    return () => {
      cancelled = true;
    };
  }, [sessionId, selectedReportId]);

  useEffect(() => {
    const positions = Object.entries(portfolioPositions ?? {}).map(([ticker, shares]) => ({
      ticker: ticker.trim().toUpperCase(),
      shares: Number(shares) || 0,
    })).filter((item) => item.ticker && item.shares > 0);

    void apiClient.syncPortfolioPositions(sessionId, positions).catch(() => {
      // keep UI responsive even when sync fails
    });
  }, [sessionId, portfolioPositions]);

  const selectedReportRecord = asRecord(selectedReport);
  const selectedReportMeta = asRecord(selectedReportRecord?.meta);
  const selectedReportHints = asRecord(selectedReportRecord?.report_hints)
    ?? asRecord(selectedReportMeta?.report_hints);
  const selectedQualityHints = asRecord(selectedReportHints?.quality);
  const selectedVerifierHints = asRecord(selectedReportHints?.verifier);
  const qualityMissing = asStringList(selectedQualityHints?.missing_requirements);
  const verifierClaims = asVerifierClaims(selectedVerifierHints?.unsupported_claims);
  const citations = Array.isArray(selectedReportRecord?.citations)
    ? (selectedReportRecord?.citations as Record<string, unknown>[])
    : [];

  const groundingRate = useMemo(() => (
    normalizeGroundingRate(selectedReportRecord?.grounding_rate)
    ?? normalizeGroundingRate(asRecord(selectedReportMeta?.grounding)?.grounding_rate)
    ?? normalizeGroundingRate(asRecord(selectedReportHints?.grounding)?.grounding_rate)
    ?? normalizeGroundingRate(asRecord(selectedQualityHints?.grounding)?.grounding_rate)
  ), [selectedQualityHints, selectedReportHints, selectedReportMeta, selectedReportRecord]);

  const showLowGroundingBanner = groundingRate !== null && groundingRate < 0.6;
  const groundingRateText = groundingRate !== null ? `${Math.round(groundingRate * 100)}%` : '--';
  const reportTicker = asString(selectedReportRecord?.ticker).toUpperCase();
  const activeTicker = asString(symbol).toUpperCase();
  const hasTickerMismatch = Boolean(
    activeTicker
    && reportTicker
    && !isReportTickerAligned(activeTicker, reportTicker),
  );

  const openQualityDrawer = useCallback((focusHint?: string | null) => {
    setQualityFocusHint(focusHint ?? null);
    setQualityDrawerOpen(true);
  }, []);

  const handleOpenInChat = useCallback(() => {
    if (!selectedReportId) return;
    navigate(`/chat?report_id=${encodeURIComponent(selectedReportId)}`);
  }, [navigate, selectedReportId]);

  return (
    <div className="space-y-4">
      {/* Breadcrumb / navigation bar */}
      <Card className="px-4 py-3">
        <div className="flex items-center justify-between gap-3">
          <div className="text-xs text-fin-muted">
            {fromDashboard
              ? '来源：仪表盘 -> 工作台'
              : '来源：侧边导航 -> 工作台'}
          </div>
          <button
            type="button"
            data-testid="workbench-back-dashboard"
            onClick={() =>
              navigate(`/dashboard/${encodeURIComponent(symbol)}`)
            }
            className="text-xs px-2.5 py-1.5 rounded-lg border border-fin-border hover:border-fin-primary/50 text-fin-text-secondary hover:text-fin-primary transition-colors"
          >
            回到上游（仪表盘）
          </button>
        </div>
      </Card>

      {/* Portfolio Summary Bar */}
      <PortfolioSummaryBar />

      {/* Quick Analysis Bar (G4) */}
      <QuickAnalysisBar defaultTicker={symbol} />

      {/* Main content: two-column layout */}
      <div className="grid lg:grid-cols-3 gap-4">
        {/* Left: Tasks + Rebalance (main, emphasized) */}
        <div className="lg:col-span-2 space-y-4">
          <TaskSection
            symbol={symbol}
            onNavigateToChat={onNavigateToChat}
          />
          <RebalanceEntryCard />
        </div>

        {/* Right: Portfolio Pie + Reports (sidebar) */}
        <div className="space-y-4">
          {/* Portfolio distribution pie chart (G4) */}
          {portfolioSummary.data && portfolioSummary.data.positions.length > 0 && (
            <PortfolioPieChart
              positions={portfolioSummary.data.positions}
              totalValue={portfolioSummary.data.total_value}
            />
          )}
          <ReportSection
            symbol={symbol}
            reports={latestReports}
            loading={loadingReports}
            selectedReportId={selectedReportId}
            onSelectReport={setSelectedReportId}
          />
        </div>
      </div>

      <Card className="p-4 space-y-3" data-testid="workbench-report-view">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div>
            <div className="text-sm font-semibold text-fin-text">工作台报告视图</div>
            <div className="text-2xs text-fin-muted mt-0.5">
              已选择报告：{selectedReportId || '--'}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="px-3 py-1.5 rounded-lg border border-fin-border text-xs text-fin-text hover:bg-fin-border/20 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              disabled={!selectedReportId}
              onClick={handleOpenInChat}
            >
              在聊天中打开
            </button>
            <button
              type="button"
              className="px-3 py-1.5 rounded-lg border border-fin-warning/40 bg-fin-warning/10 text-xs text-fin-warning hover:bg-fin-warning/20 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              onClick={() => openQualityDrawer()}
              disabled={!selectedReport || (qualityMissing.length === 0 && verifierClaims.length === 0)}
              data-testid="workbench-quality-open-drawer"
            >
              证据质量诊断
            </button>
          </div>
        </div>

        {loadingSelectedReport && (
          <div className="rounded-lg border border-fin-border bg-fin-card/60 px-4 py-5 text-sm text-fin-muted" data-testid="workbench-report-loading">
            正在加载报告详情...
          </div>
        )}

        {!loadingSelectedReport && selectedReportError && (
          <div className="rounded-lg border border-fin-danger/40 bg-fin-danger/10 px-4 py-3 text-sm text-fin-danger" data-testid="workbench-report-error">
            {selectedReportError}
          </div>
        )}

        {!loadingSelectedReport && !selectedReportError && !selectedReport && (
          <div className="rounded-lg border border-fin-border bg-fin-card/60 px-4 py-5 text-sm text-fin-muted" data-testid="workbench-report-empty">
            请先在右侧报告时间线中选择一份报告。
          </div>
        )}

        {!loadingSelectedReport && selectedReport && (
          <>
            {hasTickerMismatch && (
              <div
                className="rounded-xl border border-fin-danger/50 bg-fin-danger/10 px-4 py-3"
                data-testid="workbench-report-ticker-mismatch"
              >
                <div className="text-sm font-semibold text-fin-danger">
                  ⚠ 报告标的不匹配，结论区已禁用
                </div>
                <div className="mt-1 text-xs text-fin-text/90">
                  当前标的：{activeTicker || '--'}；报告标的：{reportTicker || '--'}。为避免串票误导，已阻断结论展示。
                </div>
              </div>
            )}

            {showLowGroundingBanner && (
              <div
                className="rounded-xl border border-yellow-400/40 bg-yellow-500/10 px-4 py-3 text-sm text-yellow-100"
                data-testid="workbench-report-grounding-warning"
              >
                <div className="font-medium">⚠ 证据溯源率偏低（{groundingRateText}）</div>
                <div className="mt-1 text-xs text-yellow-100/85">
                  当前结论中存在较多缺少直接证据锚点的断言，建议优先核对引用列表与正文摘录后再决策。
                </div>
              </div>
            )}

            {qualityMissing.length > 0 && (
              <div
                className="rounded-xl border border-fin-warning/40 bg-fin-warning/10 px-4 py-3"
                data-testid="workbench-report-quality-gap"
              >
                <div className="text-sm font-semibold text-fin-warning">证据不足（质量门槛未满足）</div>
                <div className="mt-1 text-xs text-fin-text/80">
                  可直接定位到引用片段核对，不需要“问这条”。
                </div>
                <div className="mt-2 space-y-2">
                  {qualityMissing.slice(0, 6).map((item, idx) => (
                    <div key={`${idx}-${item}`} className="flex items-start gap-2 text-xs">
                      <span className="text-fin-warning mt-0.5">•</span>
                      <span className="flex-1 text-fin-text/85">{item}</span>
                      <button
                        type="button"
                        className="shrink-0 px-2 py-0.5 rounded border border-fin-border text-fin-primary hover:bg-fin-primary/10 transition-colors"
                        onClick={() => openQualityDrawer(resolveFocusHintFromRequirement(item))}
                        data-testid={`workbench-quality-focus-${idx}`}
                      >
                        查看引用片段
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {verifierClaims.length > 0 && (
              <div
                className="rounded-xl border border-fin-danger/40 bg-fin-danger/10 px-4 py-3"
                data-testid="workbench-report-verifier-gap"
              >
                <div className="text-sm font-semibold text-fin-danger">
                  二次事实核查发现 {verifierClaims.length} 条断言缺口
                </div>
                <div className="mt-1 text-xs text-fin-text/85">
                  建议优先点击“证据质量诊断”定位对应引用片段。
                </div>
              </div>
            )}

            {hasTickerMismatch ? (
              <div
                className="rounded-xl border border-fin-border bg-fin-card/60 px-4 py-6 text-sm text-fin-muted"
                data-testid="workbench-report-conclusion-disabled"
              >
                结论区已禁用：请先修复串票后再查看完整深度报告。
              </div>
            ) : (
              <ReportView report={selectedReport} />
            )}
          </>
        )}
      </Card>

      <WorkbenchQualityDrawer
        open={qualityDrawerOpen}
        onClose={() => setQualityDrawerOpen(false)}
        qualityMissing={qualityMissing}
        verifierClaims={verifierClaims}
        citations={citations}
        initialFocusHint={qualityFocusHint}
      />
    </div>
  );
}

export default Workbench;
