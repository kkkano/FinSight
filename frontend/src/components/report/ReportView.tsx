import React, { useEffect, useMemo, useState } from 'react';
import type { ReportIR, ReportSection as ReportSectionType } from '../../types/index';
import { Maximize2, X } from 'lucide-react';
import { apiClient } from '../../api/client';
import { deriveUserIdFromSessionId, useStore } from '../../store/useStore';
import {
  normalizeAnchor,
  buildSourceSummary,
  buildEvidenceBadges,
  extractCatalystItems,
  extractMetrics,
  extractReportHints,
  extractAgentDetailSections,
  normalizeReportErrors,
  buildReportMessages,
} from './ReportUtils';
import { ReportHeader } from './ReportHeader';
import { ReportAgentCard, ReportEvidencePoolSection } from './ReportAgentCard';
import {
  ConfidenceMeter,
  AgentStatusGrid,
  RiskCatalystMetrics,
  SynthesisReportBlock,
} from './ReportCharts';
import { useToast } from '../ui';

export interface ReportViewProps {
  report: ReportIR;
}

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
  const [activeSection, setActiveSection] = useState<number | null>(null);
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
  const catalystItems = useMemo(() => extractCatalystItems(sections), [sections]);
  const metricItems = useMemo(() => extractMetrics(sections), [sections]);
  const sourceSummary = useMemo(() => buildSourceSummary(report.citations), [report.citations]);
  const evidenceBadges = useMemo(() => buildEvidenceBadges(report.citations || []), [report.citations]);
  const reportHints = useMemo(() => extractReportHints(report), [report]);
  const agentDetailSections = useMemo(() => extractAgentDetailSections(report), [report]);

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

  /* ---------------------------------------------------------------- */
  /*  Effects                                                          */
  /* ---------------------------------------------------------------- */

  useEffect(() => {
    let mounted = true;

    setWatchlisted(false);
    setSubscribed(false);
    setActiveSection(null);
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
    const root = document.getElementById('chat-scroll-container');
    const sectionNodes = Array.from(
      document.querySelectorAll(`[data-report-anchor="${anchorPrefix}"]`),
    ) as HTMLElement[];

    if (sectionNodes.length === 0) return;

    const ratios = new Map<Element, number>();

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          ratios.set(entry.target, entry.isIntersecting ? entry.intersectionRatio : 0);
        });

        let bestOrder: number | null = null;
        let bestRatio = 0;

        ratios.forEach((ratio, element) => {
          if (ratio <= bestRatio) return;
          const order = Number((element as HTMLElement).dataset.sectionOrder);
          if (Number.isNaN(order)) return;
          bestOrder = order;
          bestRatio = ratio;
        });

        if (bestOrder !== null) {
          setActiveSection((prev) => (prev === bestOrder ? prev : bestOrder));
        }
      },
      {
        root,
        rootMargin: '-20% 0px -65% 0px',
        threshold: [0, 0.25, 0.5, 0.75, 1],
      },
    );

    sectionNodes.forEach((node) => {
      ratios.set(node, 0);
      observer.observe(node);
    });

    return () => observer.disconnect();
  }, [anchorPrefix]);

  useEffect(() => {
    if (isFullscreen) {
      setExpandedSections((prev) => ({ ...prev, synthesis: true }));
    }
  }, [isFullscreen]);

  /* ---------------------------------------------------------------- */
  /*  Handlers                                                         */
  /* ---------------------------------------------------------------- */

  const handleJumpToSection = (order: number) => {
    setActiveSection(order);
    setExpandedSections((prev) => ({ ...prev, [order]: true }));
    const target = document.getElementById(`${anchorPrefix}-section-${order}`);
    if (target) {
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  };

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

  const toggleSection = (order: number) => {
    setActiveSection(order);
    setExpandedSections((prev) => ({ ...prev, [order]: !prev[order] }));
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

            <div className="space-y-4">
              <SynthesisReportBlock
                synthesisReport={(report as any).synthesis_report || ''}
                isExpanded={expandedSections['synthesis'] ?? false}
                onToggle={toggleSynthesis}
                onExpand={expandSynthesis}
                onCollapse={collapseSynthesis}
              />

              <ReportAgentCard
                agentDetailSections={agentDetailSections as ReportSectionType[]}
                expandedSections={expandedSections}
                onToggleSection={toggleSection}
              />

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
    <div className="bg-white/90 dark:bg-fin-panel/90 rounded-2xl shadow-[0_10px_30px_-18px_rgba(15,23,42,0.45)] border border-slate-200/80 dark:border-slate-700/70 overflow-hidden max-w-4xl mx-auto my-4 relative">
      {/* Fullscreen button */}
      <button
        onClick={() => setIsFullscreen(true)}
        className="absolute bottom-4 right-4 z-10 p-2 bg-slate-100 dark:bg-slate-800 rounded-lg hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors shadow-sm border border-slate-200 dark:border-slate-700"
        title="全屏查看报告"
      >
        <Maximize2 size={16} className="text-slate-600 dark:text-slate-300" />
      </button>

      {/* Header area */}
      <div className="p-6 border-b border-slate-200/80 dark:border-slate-700/70 bg-gradient-to-r from-blue-50 via-white to-indigo-50 dark:from-slate-900 dark:via-slate-900 dark:to-slate-900 relative">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <ReportHeader
            report={report}
            formattedDate={formattedDate}
            evidenceBadges={evidenceBadges}
            sourceSummary={sourceSummary}
            reportHints={reportHints}
            warningNode={warningNode}
          />
        </div>

        {/* Agent execution overview + Confidence meter */}
        <div className="mt-5 grid gap-4 md:grid-cols-[1fr_280px]">
          <div className="rounded-xl border border-slate-200/80 dark:border-slate-700/60 bg-white/70 dark:bg-slate-900/60 p-4">
            <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-300 mb-3">
              Agent 执行概览
            </div>
            <AgentStatusGrid report={report} />
          </div>
          <ConfidenceMeter score={report.confidence_score} />
        </div>

        {warningNode && <div className="mt-4">{warningNode}</div>}

        <RiskCatalystMetrics
          risks={report.risks || []}
          catalystItems={catalystItems}
          metricItems={metricItems}
        />

        {/* Mobile section nav */}
        {sections.length > 0 && (
          <div className="mt-4 flex flex-wrap gap-2 lg:hidden">
            {sections.map((section) => (
              <button
                key={section.order}
                type="button"
                onClick={() => handleJumpToSection(section.order)}
                className={`px-3 py-1 rounded-full border text-[11px] transition ${activeSection === section.order
                  ? 'border-blue-400 text-blue-600 bg-blue-50/70 dark:border-blue-500/60 dark:text-blue-200'
                  : 'border-slate-200 dark:border-slate-700 text-slate-500 dark:text-slate-300 hover:border-blue-400 hover:text-blue-600'
                  }`}
              >
                {section.order}. {section.title}
              </button>
            ))}
          </div>
        )}

      </div>

      {/* Body: sidebar + content */}
      <div className="p-6 bg-slate-50/60 dark:bg-slate-900/50">
        <div className="flex flex-col lg:flex-row gap-6">
          {/* Desktop sidebar */}
          <aside className="hidden lg:block w-48 shrink-0">
            <div className="sticky top-6 space-y-3">
              <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-300">
                章节目录
              </div>
              <div className="space-y-2">
                {sections.map((section) => {
                  const agentName = (section as any).agent_name;
                  const hasError = (section as any).error;
                  return (
                    <button
                      key={section.order}
                      type="button"
                      onClick={() => handleJumpToSection(section.order)}
                      className={`w-full text-left px-3 py-2 rounded-lg border text-[11px] transition ${activeSection === section.order
                        ? 'border-blue-400 text-blue-600 bg-blue-50/70 dark:border-blue-500/60 dark:text-blue-200'
                        : hasError
                          ? 'border-amber-300 dark:border-amber-700 text-amber-600 dark:text-amber-300'
                          : 'border-slate-200 dark:border-slate-700 text-slate-500 dark:text-slate-300 hover:border-blue-400 hover:text-blue-600'
                        }`}
                    >
                      <div><span className="font-semibold">{section.order}.</span> {section.title}</div>
                      {agentName && <div className="text-[9px] text-slate-400 mt-0.5">{agentName}</div>}
                    </button>
                  );
                })}
              </div>
            </div>
          </aside>

          {/* Main content */}
          <div className="flex-1 min-w-0 space-y-4">
            <SynthesisReportBlock
              synthesisReport={(report as any).synthesis_report || ''}
              isExpanded={expandedSections['synthesis'] ?? false}
              onToggle={toggleSynthesis}
              onExpand={expandSynthesis}
              onCollapse={collapseSynthesis}
            />

            <ReportAgentCard
              agentDetailSections={agentDetailSections as ReportSectionType[]}
              expandedSections={expandedSections}
              onToggleSection={toggleSection}
            />

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

      {/* Footer */}
      <div className="px-6 py-4 bg-slate-50 dark:bg-slate-900/80 border-t border-slate-200/80 dark:border-slate-700/70 flex flex-wrap items-center justify-between gap-3 text-[11px] text-slate-500 dark:text-slate-400">
        <span>Generated by FinSight AI ? Deep Research Engine</span>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={handleExportPdf}
            disabled={actionState.exporting}
            className="px-3 py-1 rounded-full border border-slate-200 dark:border-slate-700 bg-white/80 dark:bg-slate-900 text-slate-600 dark:text-slate-300 text-[11px] hover:border-blue-400 hover:text-blue-600 transition disabled:opacity-60"
          >
            {actionState.exporting ? 'Exporting...' : 'Export PDF'}
          </button>
          <button
            type="button"
            onClick={handleWatchlist}
            disabled={actionState.watchlist}
            className="px-3 py-1 rounded-full border border-slate-200 dark:border-slate-700 bg-white/80 dark:bg-slate-900 text-slate-600 dark:text-slate-300 text-[11px] hover:border-blue-400 hover:text-blue-600 transition disabled:opacity-60"
          >
            {watchlisted ? 'Remove Watchlist' : 'Save to Watchlist'}
          </button>
          <button
            type="button"
            onClick={handleSubscribe}
            disabled={actionState.subscribe}
            className="px-3 py-1 rounded-full border border-blue-200 dark:border-blue-700/60 bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-200 text-[11px] hover:opacity-90 transition disabled:opacity-60"
          >
            {subscribed ? 'Subscribed' : 'Subscribe Alerts'}
          </button>
          <span className="text-2xs text-slate-400">ID: {report.report_id}</span>
        </div>
      </div>
    </div>
  );
};
