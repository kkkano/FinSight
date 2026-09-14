import React, { useEffect, useMemo, useState } from 'react';
import type {
  EvidenceLedger,
  QueryCoverage,
  ReportIR,
} from '../../types/index';
import { AlertTriangle, Link2Off, Maximize2, Share2, X } from 'lucide-react';
import { apiClient } from '../../api/client';
import { useDashboardStore } from '../../store/dashboardStore';
import {
  normalizeAnchor,
  buildSourceSummary,
  buildEvidenceBadges,
  extractMetrics,
  extractReportHints,
  normalizeReportErrors,
} from './ReportUtils';
import { ReportHeader } from './ReportHeader';
import { ReportEvidencePoolSection } from './ReportAgentCard';
import { SynthesisReportBlock } from './ReportCharts';
import { EvidenceLedgerPanel } from './EvidenceLedgerPanel';
import { ReportCockpit } from './ReportCockpit';
import { FactCheckCard } from './FactCheckCard';
import { QualityBadge } from './QualityBadge';
import { useToast } from '../ui';

export interface ReportViewProps {
  report: ReportIR;
  readOnly?: boolean;
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

export const ReportView: React.FC<ReportViewProps> = ({ report, readOnly = false }) => {
  const watchlist = useDashboardStore((state) => state.watchlist);
  const initWatchlist = useDashboardStore((state) => state.initWatchlist);
  const addWatchItemApi = useDashboardStore((state) => state.addWatchItemApi);
  const removeWatchItemApi = useDashboardStore((state) => state.removeWatchItemApi);
  const { toast } = useToast();

  /* ---------------------------------------------------------------- */
  /*  State                                                            */
  /* ---------------------------------------------------------------- */

  const [expandedSections, setExpandedSections] = useState<Record<string | number, boolean>>({
    ...(report.sections ?? []).reduce((acc, sec) => ({ ...acc, [sec.order]: true }), {}),
    synthesis: true,
  });
  const [activeCitation, setActiveCitation] = useState<string | null>(null);
  const [actionState, setActionState] = useState({
    watchlist: false,
    share: false,
  });
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [shareUrl, setShareUrl] = useState<string | null>(null);

  /* ---------------------------------------------------------------- */
  /*  Derived / memoized values                                        */
  /* ---------------------------------------------------------------- */

  const anchorPrefix = useMemo(() => normalizeAnchor(report.report_id || report.ticker || 'report'), [report.report_id, report.ticker]);
  const pad2 = (n: number) => String(n).padStart(2, '0');
  // P0-4: 显示完整时间，让用户知道数据时效（避免拿过时数据决策）
  const formattedDate = useMemo(() => {
    const date = new Date(report.generated_at);
    if (Number.isNaN(date.getTime())) return report.generated_at;
    return `基于 ${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())} ${pad2(date.getHours())}:${pad2(date.getMinutes())} 数据生成`;
  }, [report.generated_at]);
  // P0-4: 紧凑场景用的短格式 "2026-05-29 14:32"（cockpit 单行 metadata）
  const formattedDateShort = useMemo(() => {
    const date = new Date(report.generated_at);
    if (Number.isNaN(date.getTime())) return report.generated_at;
    return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())} ${pad2(date.getHours())}:${pad2(date.getMinutes())}`;
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
  const hasResearchArtifacts = Boolean(researchArtifacts.evidenceLedger);
  const watchlisted = useMemo(
    () => watchlist.some((item) => item.symbol.toUpperCase() === report.ticker?.toUpperCase()),
    [report.ticker, watchlist],
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
    if (readOnly) return undefined;

    setActiveCitation(null);
    void initWatchlist();
  }, [initWatchlist, readOnly, report.report_id]);

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

  const handleWatchlist = async () => {
    if (actionState.watchlist) return;
    setActionState((prev) => ({ ...prev, watchlist: true }));
    try {
      if (watchlisted) {
        await removeWatchItemApi(report.ticker);
        toast({ type: 'info', title: '已移除自选' });
      } else {
        await addWatchItemApi(report.ticker);
        toast({ type: 'success', title: '已加入自选' });
      }
    } catch {
      toast({ type: 'error', title: '自选更新失败' });
    } finally {
      setActionState((prev) => ({ ...prev, watchlist: false }));
    }
  };

  const handleShare = async () => {
    if (actionState.share) return;
    setActionState((prev) => ({ ...prev, share: true }));
    try {
      const response = shareUrl
        ? { share_url: shareUrl }
        : await apiClient.createReportShare(report.report_id);
      const absoluteUrl = new URL(response.share_url, window.location.origin).toString();
      await navigator.clipboard.writeText(absoluteUrl);
      setShareUrl(absoluteUrl);
      toast({ type: 'success', title: '分享链接已复制' });
    } catch {
      toast({ type: 'error', title: '分享链接创建或复制失败' });
    } finally {
      setActionState((prev) => ({ ...prev, share: false }));
    }
  };

  const handleRevokeShare = async () => {
    if (actionState.share) return;
    setActionState((prev) => ({ ...prev, share: true }));
    try {
      await apiClient.revokeReportShare(report.report_id);
      setShareUrl(null);
      toast({ type: 'info', title: '分享链接已撤销' });
    } catch {
      toast({ type: 'error', title: '撤销分享失败' });
    } finally {
      setActionState((prev) => ({ ...prev, share: false }));
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

            {/* 全屏模式沿用同一质量徽章。 */}
            {report.report_quality && <QualityBadge quality={report.report_quality} />}

            {queryCoverageWarningNode}

            <div className="space-y-4">
              <SynthesisReportBlock
                synthesisReport={(report as any).synthesis_report || ''}
                isExpanded={expandedSections['synthesis'] ?? false}
                onToggle={toggleSynthesis}
                onExpand={expandSynthesis}
                onCollapse={collapseSynthesis}
              />

              {report.fact_check && <FactCheckCard factCheck={report.fact_check} />}

              {hasResearchArtifacts && (
                <div className="space-y-3">
                  <EvidenceLedgerPanel ledger={researchArtifacts.evidenceLedger} />
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
      {!readOnly && (
        <button
          onClick={() => setIsFullscreen(true)}
          className="absolute bottom-4 right-4 z-10 p-2 bg-fin-bg-secondary rounded-lg hover:bg-fin-hover transition-colors shadow-sm border border-fin-border"
          title="全屏查看报告"
        >
          <Maximize2 size={16} className="text-fin-text-secondary" />
        </button>
      )}

      {/* ===== 方案A 紧凑指挥台主体 ===== */}
      <div className="p-6">
        <ReportCockpit
          report={report}
          formattedDate={formattedDateShort}
          evidenceBadges={evidenceBadges}
          metricItems={metricItems}
        />

        {/* P2-12 质量徽章：报告顶部一眼可见的质量门控状态 */}
        {report.report_quality && (
          <div className="mt-3">
            <QualityBadge quality={report.report_quality} />
          </div>
        )}


        {queryCoverageWarningNode && <div className="mt-4">{queryCoverageWarningNode}</div>}
        {warningNode && <div className="mt-4">{warningNode}</div>}

        {/* 深入区：研究产物 / 完整证据账本（Agent 分析详情已并入核心观点去重） */}
        <div className="mt-6 space-y-4">
          {report.fact_check && <FactCheckCard factCheck={report.fact_check} />}

          {hasResearchArtifacts && (
            <div className="space-y-3">
              <EvidenceLedgerPanel ledger={researchArtifacts.evidenceLedger} />
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
      {!readOnly && (
        <div className="px-6 py-4 bg-fin-bg-secondary border-t border-fin-border flex flex-wrap items-center justify-between gap-3 text-[11px] text-fin-muted">
          <span>Generated by FinSight AI ? Deep Research Engine</span>
          <div className="flex flex-wrap items-center gap-2">
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
              onClick={handleShare}
              disabled={actionState.share}
              className="inline-flex items-center gap-1 px-3 py-1 rounded-full border border-fin-primary/30 bg-fin-primary/10 text-fin-primary text-[11px] hover:opacity-90 transition disabled:opacity-60"
            >
              <Share2 size={12} />
              {actionState.share ? '处理中…' : shareUrl ? '复制分享链接' : '分享链接'}
            </button>
            {shareUrl && (
              <button
                type="button"
                onClick={handleRevokeShare}
                disabled={actionState.share}
                className="inline-flex items-center gap-1 px-3 py-1 rounded-full border border-fin-danger/30 bg-fin-danger/10 text-fin-danger text-[11px] hover:opacity-90 transition disabled:opacity-60"
              >
                <Link2Off size={12} />
                撤销分享
              </button>
            )}
            <span className="text-2xs text-fin-muted">ID: {report.report_id}</span>
          </div>
        </div>
      )}
    </div>
  );
};
