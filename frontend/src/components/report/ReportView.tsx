import React, { useEffect, useMemo, useState } from 'react';
import type {
  DebateArtifact,
  EvidenceLedger,
  HoldingsInsight,
  QueryCoverage,
  ReportIR,
} from '../../types/index';
import { AlertTriangle, Maximize2, X } from 'lucide-react';
import { apiClient } from '../../api/client';
import { deriveUserIdFromSessionId, useStore } from '../../store/useStore';
import {
  normalizeAnchor,
  buildSourceSummary,
  buildEvidenceBadges,
  extractMetrics,
  extractReportHints,
  normalizeReportErrors,
  buildReportMessages,
} from './ReportUtils';
import { ReportHeader } from './ReportHeader';
import { ReportEvidencePoolSection } from './ReportAgentCard';
import { SynthesisReportBlock } from './ReportCharts';
import { EvidenceLedgerPanel } from './EvidenceLedgerPanel';
import { ReportCockpit } from './ReportCockpit';
import { DebateScorecard } from './DebateScorecard';
import { HoldingsWatchPanel } from './HoldingsWatchPanel';
import { useToast } from '../ui';

export interface ReportViewProps {
  report: ReportIR;
}

const readObject = (value: unknown): Record<string, any> | null => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  return value as Record<string, any>;
};

const firstObject = <T,>(...values: unknown[]): T | null => {
  for (const value of values) {
    if (readObject(value)) return value as T;
  }
  return null;
};

const readReportArtifacts = (report: ReportIR): Record<string, any> => {
  const direct = readObject(report.artifacts);
  if (direct) return direct;

  const meta = readObject(report.meta);
  const metaArtifacts = readObject(meta?.artifacts);
  if (metaArtifacts) return metaArtifacts;

  const dataContext = readObject(meta?.data_context);
  const contextArtifacts = readObject(dataContext?.artifacts);
  if (contextArtifacts) return contextArtifacts;

  return {};
};

const formatCoverageTarget = (target: string | Record<string, unknown>): string => {
  if (typeof target === 'string') return target;
  const candidate =
    target.target ||
    target.question ||
    target.query ||
    target.label ||
    target.name ||
    target.id ||
    '未命名目标';
  return String(candidate);
};

export const ReportView: React.FC<ReportViewProps> = ({ report }) => {
  const { subscriptionEmail, sessionId } = useStore();
  const { toast } = useToast();
  const userId = useMemo(() => deriveUserIdFromSessionId(sessionId), [sessionId]);

  /* ---------------------------------------------------------------- */
  /*  State                                                            */
  /* ---------------------------------------------------------------- */

  const [expandedSections, setExpandedSections] = useState<Record<string | number, boolean>>({
    ...(report.sections ?? []).reduce((acc, sec) => ({ ...acc, [sec.order]: true }), {}),
    synthesis: true,
  });
  const [activeCitation, setActiveCitation] = useState<string | null>(null);
  const [watchlisted, setWatchlisted] = useState(false);
  const [subscribed, setSubscribed] = useState(false);
  const [actionState, setActionState] = useState({ exporting: false, watchlist: false, subscribe: false });
  const [isFullscreen, setIsFullscreen] = useState(false);

  /* ---------------------------------------------------------------- */
  /*  Derived / memoized values                                        */
  /* ---------------------------------------------------------------- */

  const anchorPrefix = useMemo(() => normalizeAnchor(report.report_id || report.ticker || 'report'), [report.report_id, report.ticker]);
  const formattedDate = useMemo(() => {
    const date = new Date(report.generated_at);
    return Number.isNaN(date.getTime()) ? report.generated_at : date.toLocaleDateString();
  }, [report.generated_at]);

  const sections = useMemo(() => report.sections ?? [], [report.sections]);
  const metricItems = useMemo(() => extractMetrics(sections), [sections]);
  const sourceSummary = useMemo(() => buildSourceSummary(report.citations), [report.citations]);
  const evidenceBadges = useMemo(() => buildEvidenceBadges(report.citations || []), [report.citations]);
  const reportHints = useMemo(() => extractReportHints(report), [report]);
  const researchArtifacts = useMemo(() => {
    const artifacts = readReportArtifacts(report);
    const meta = readObject(report.meta);
    const dataContext = readObject(meta?.data_context);
    const reportHintsObject = readObject(report.report_hints);

    return {
      evidenceLedger: firstObject<EvidenceLedger>(
        report.evidence_ledger,
        artifacts.evidence_ledger,
        meta?.evidence_ledger,
        dataContext?.evidence_ledger,
      ),
      debateArtifact: firstObject<DebateArtifact>(
        report.debate,
        artifacts.debate,
        meta?.debate,
        dataContext?.debate,
      ),
      holdingsInsight: firstObject<HoldingsInsight>(
        report.holdings_insight,
        artifacts.holdings_insight,
        artifacts.holdings,
        meta?.holdings_insight,
        dataContext?.holdings_insight,
        dataContext?.holdings,
      ),
      queryCoverage: firstObject<QueryCoverage>(
        report.query_coverage,
        artifacts.query_coverage,
        reportHintsObject?.query_coverage,
        meta?.query_coverage,
        dataContext?.query_coverage,
      ),
    };
  }, [report]);

  const unansweredTargets = useMemo(
    () => researchArtifacts.queryCoverage?.unanswered_targets || [],
    [researchArtifacts.queryCoverage],
  );
  const hasResearchArtifacts = Boolean(
    researchArtifacts.evidenceLedger ||
    researchArtifacts.debateArtifact ||
    researchArtifacts.holdingsInsight,
  );

  const { classifiedErrors, warningText, shouldShowWarning, formattedErrors } = useMemo(
    () => normalizeReportErrors(report),
    [report],
  );

  /* ---------------------------------------------------------------- */
  /*  Warning node                                                     */
  /* ---------------------------------------------------------------- */

  const warningNode = shouldShowWarning ? (
    <div className="rounded-lg border border-amber-200 bg-amber-50/80 text-amber-700 px-4 py-3 text-xs dark:border-amber-800/60 dark:bg-amber-900/20 dark:text-amber-200">
      <div className="font-semibold">⚠️ 报告提示</div>
      {warningText && <div className="mt-1">{warningText}</div>}
      {formattedErrors.length > 0 && (
        <ul className="mt-2 list-disc list-inside space-y-1">
          {classifiedErrors.map((err, idx) => (
            <li key={`${err.text}-${idx}`} className="flex items-start gap-2">
              <span className={`px-1.5 py-0.5 rounded-full text-2xs ${err.tone}`}>{err.label}</span>
              <span className="flex-1">{err.text}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  ) : null;

  const queryCoverageWarningNode = unansweredTargets.length > 0 ? (
    <div className="rounded-lg border border-amber-200 bg-amber-50/90 px-4 py-3 text-xs text-amber-800 dark:border-amber-900/60 dark:bg-amber-900/20 dark:text-amber-200">
      <div className="flex items-center gap-2 font-semibold">
        <AlertTriangle size={14} />
        查询覆盖缺口
        <span className="ml-auto font-normal tabular-nums">{unansweredTargets.length} pending</span>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {unansweredTargets.slice(0, 6).map((target, index) => (
          <span
            key={`${formatCoverageTarget(target)}-${index}`}
            className="rounded border border-amber-200/80 bg-white/70 px-2 py-0.5 text-2xs text-amber-800 dark:border-amber-800/70 dark:bg-amber-950/30 dark:text-amber-100"
          >
            {formatCoverageTarget(target)}
          </span>
        ))}
        {unansweredTargets.length > 6 && (
          <span className="px-2 py-0.5 text-2xs text-amber-700 dark:text-amber-200">
            +{unansweredTargets.length - 6}
          </span>
        )}
      </div>
    </div>
  ) : null;

  /* ---------------------------------------------------------------- */
  /*  Effects                                                          */
  /* ---------------------------------------------------------------- */

  useEffect(() => {
    let mounted = true;

    setWatchlisted(false);
    setSubscribed(false);
    setActiveCitation(null);

    apiClient
      .getUserProfile(userId)
      .then((response) => {
        if (!mounted || !response?.success) return;
        const list = response.profile?.watchlist || [];
        if (Array.isArray(list) && list.includes(report.ticker)) {
          setWatchlisted(true);
        }
      })
      .catch(() => undefined);

    if (subscriptionEmail) {
      apiClient
        .listSubscriptions(subscriptionEmail)
        .then((response) => {
          if (!mounted || !response?.success) return;
          const list = response.subscriptions || [];
          const ticker = report.ticker?.toUpperCase();
          if (ticker && Array.isArray(list)) {
            const matched = list.some((sub: { ticker?: string }) => sub.ticker?.toUpperCase() === ticker);
            setSubscribed(matched);
          }
        })
        .catch(() => undefined);
    }

    return () => {
      mounted = false;
    };
  }, [report.ticker, report.report_id, subscriptionEmail, userId]);

  useEffect(() => {
    if (isFullscreen) {
      setExpandedSections((prev) => ({ ...prev, synthesis: true }));
    }
  }, [isFullscreen]);

  /* ---------------------------------------------------------------- */
  /*  Handlers                                                         */
  /* ---------------------------------------------------------------- */

  const handleJumpToCitation = (ref: string) => {
    setActiveCitation(ref);
    const target = document.getElementById(`${anchorPrefix}-citation-${ref}`);
    if (target) {
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  };

  const handleExportPdf = async () => {
    if (actionState.exporting) return;
    setActionState((prev) => ({ ...prev, exporting: true }));
    try {
      const messages = buildReportMessages(report);
      const blob = await apiClient.exportPDF(messages, [], `${report.ticker} Report`);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `report_${report.ticker}_${formattedDate}.pdf`;
      a.click();
      window.URL.revokeObjectURL(url);
      toast({ type: 'success', title: 'PDF 已导出' });
    } catch {
      toast({ type: 'error', title: 'PDF 导出失败' });
    } finally {
      setActionState((prev) => ({ ...prev, exporting: false }));
    }
  };

  const handleWatchlist = async () => {
    if (actionState.watchlist) return;
    setActionState((prev) => ({ ...prev, watchlist: true }));
    try {
      const payload = { user_id: userId, ticker: report.ticker };
      if (watchlisted) {
        await apiClient.removeWatchlist(payload);
        setWatchlisted(false);
        toast({ type: 'info', title: '已移除自选' });
      } else {
        await apiClient.addWatchlist(payload);
        setWatchlisted(true);
        toast({ type: 'success', title: '已加入自选' });
      }
    } catch {
      toast({ type: 'error', title: '自选更新失败' });
    } finally {
      setActionState((prev) => ({ ...prev, watchlist: false }));
    }
  };

  const handleSubscribe = async () => {
    if (actionState.subscribe) return;
    const email = subscriptionEmail.trim();
    if (!email) {
      toast({ type: 'info', title: '请先在设置中填写订阅邮箱' });
      return;
    }
    if (subscribed) {
      toast({ type: 'info', title: '已订阅提醒' });
      return;
    }
    setActionState((prev) => ({ ...prev, subscribe: true }));
    try {
      await apiClient.subscribe({
        email,
        ticker: report.ticker,
        alert_types: ['price_change', 'news'],
      });
      setSubscribed(true);
      toast({ type: 'success', title: '提醒订阅成功' });
    } catch {
      toast({ type: 'error', title: '订阅失败' });
    } finally {
      setActionState((prev) => ({ ...prev, subscribe: false }));
    }
  };

  const toggleSynthesis = () => {
    setExpandedSections((prev) => ({ ...prev, synthesis: !prev.synthesis }));
  };

  const expandSynthesis = () => {
    setExpandedSections((prev) => ({ ...prev, synthesis: true }));
  };

  const collapseSynthesis = () => {
    setExpandedSections((prev) => ({ ...prev, synthesis: false }));
  };

  /* ---------------------------------------------------------------- */
  /*  Fullscreen mode render                                           */
  /* ---------------------------------------------------------------- */

  if (isFullscreen) {
    return (
      <div className="fixed inset-0 z-50 bg-white dark:bg-slate-900 overflow-auto">
        <button
          onClick={() => setIsFullscreen(false)}
          className="fixed top-4 right-4 z-[60] p-2 bg-slate-200 dark:bg-slate-700 rounded-full hover:bg-slate-300 dark:hover:bg-slate-600 transition-colors"
          title="退出全屏"
        >
          <X size={20} className="text-slate-700 dark:text-slate-200" />
        </button>
        <div className="p-8 max-w-5xl mx-auto">
          <div className="space-y-6">
            <ReportHeader
              report={report}
              formattedDate={formattedDate}
              evidenceBadges={evidenceBadges}
              sourceSummary={sourceSummary}
              reportHints={reportHints}
              warningNode={warningNode}
              fullscreen
            />

            {queryCoverageWarningNode}

            <div className="space-y-4">
              <SynthesisReportBlock
                synthesisReport={(report as any).synthesis_report || ''}
                isExpanded={expandedSections['synthesis'] ?? false}
                onToggle={toggleSynthesis}
                onExpand={expandSynthesis}
                onCollapse={collapseSynthesis}
              />

              {hasResearchArtifacts && (
                <div className="space-y-3">
                  <EvidenceLedgerPanel ledger={researchArtifacts.evidenceLedger} />
                  <DebateScorecard debate={researchArtifacts.debateArtifact} />
                  <HoldingsWatchPanel holdings={researchArtifacts.holdingsInsight} />
                </div>
              )}

              <ReportEvidencePoolSection
                citations={report.citations}
                sourceSummary={sourceSummary}
                anchorPrefix={anchorPrefix}
                activeCitation={activeCitation}
                onSelectCitation={setActiveCitation}
                onJumpToCitation={handleJumpToCitation}
              />
            </div>
          </div>
        </div>
      </div>
    );
  }

  /* ---------------------------------------------------------------- */
  /*  Normal (card) mode render                                        */
  /* ---------------------------------------------------------------- */

  return (
    <div className="bg-fin-panel rounded-2xl shadow-[0_10px_30px_-18px_rgba(15,23,42,0.45)] border border-fin-border overflow-hidden max-w-4xl mx-auto my-4 relative">
      {/* Fullscreen button */}
      <button
        onClick={() => setIsFullscreen(true)}
        className="absolute bottom-4 right-4 z-10 p-2 bg-fin-bg-secondary rounded-lg hover:bg-fin-hover transition-colors shadow-sm border border-fin-border"
        title="全屏查看报告"
      >
        <Maximize2 size={16} className="text-fin-text-secondary" />
      </button>

      {/* ===== 方案A 紧凑指挥台主体 ===== */}
      <div className="p-6">
        <ReportCockpit
          report={report}
          formattedDate={formattedDate}
          evidenceBadges={evidenceBadges}
          metricItems={metricItems}
        />

        {queryCoverageWarningNode && <div className="mt-4">{queryCoverageWarningNode}</div>}
        {warningNode && <div className="mt-4">{warningNode}</div>}

        {/* 深入区：研究产物 / 完整证据账本（Agent 分析详情已并入核心观点去重） */}
        <div className="mt-6 space-y-4">
          {hasResearchArtifacts && (
            <div className="space-y-3">
              <EvidenceLedgerPanel ledger={researchArtifacts.evidenceLedger} />
              <DebateScorecard debate={researchArtifacts.debateArtifact} />
              <HoldingsWatchPanel holdings={researchArtifacts.holdingsInsight} />
            </div>
          )}

          <ReportEvidencePoolSection
            citations={report.citations}
            sourceSummary={sourceSummary}
            anchorPrefix={anchorPrefix}
            activeCitation={activeCitation}
            onSelectCitation={setActiveCitation}
            onJumpToCitation={handleJumpToCitation}
          />
        </div>
      </div>

      {/* Footer */}
      <div className="px-6 py-4 bg-fin-bg-secondary border-t border-fin-border flex flex-wrap items-center justify-between gap-3 text-[11px] text-fin-muted">
        <span>Generated by FinSight AI ? Deep Research Engine</span>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={handleExportPdf}
            disabled={actionState.exporting}
            className="px-3 py-1 rounded-full border border-fin-border bg-fin-card text-fin-text-secondary text-[11px] hover:border-fin-primary hover:text-fin-primary transition disabled:opacity-60"
          >
            {actionState.exporting ? 'Exporting...' : 'Export PDF'}
          </button>
          <button
            type="button"
            onClick={handleWatchlist}
            disabled={actionState.watchlist}
            className="px-3 py-1 rounded-full border border-fin-border bg-fin-card text-fin-text-secondary text-[11px] hover:border-fin-primary hover:text-fin-primary transition disabled:opacity-60"
          >
            {watchlisted ? 'Remove Watchlist' : 'Save to Watchlist'}
          </button>
          <button
            type="button"
            onClick={handleSubscribe}
            disabled={actionState.subscribe}
            className="px-3 py-1 rounded-full border border-fin-primary/30 bg-fin-primary/10 text-fin-primary text-[11px] hover:opacity-90 transition disabled:opacity-60"
          >
            {subscribed ? 'Subscribed' : 'Subscribe Alerts'}
          </button>
          <span className="text-2xs text-fin-muted">ID: {report.report_id}</span>
        </div>
      </div>
    </div>
  );
};
