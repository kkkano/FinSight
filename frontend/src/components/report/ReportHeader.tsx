import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { normalizeMarkdown } from '../../utils/markdown';
import type { ReportIR, Sentiment, CoreViewpoint } from '../../types/index';
import { TrendingUp, ChevronDown, ChevronUp } from 'lucide-react';
import type { BadgeInfo, ReportHints } from './ReportUtils';

/* ------------------------------------------------------------------ */
/*  Small badge sub-components                                         */
/* ------------------------------------------------------------------ */

const SentimentBadge: React.FC<{ sentiment: Sentiment; confidence: number }> = ({ sentiment, confidence }) => {
  const colors: Record<Sentiment, string> = {
    bullish: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-200',
    bearish: 'bg-rose-100 text-rose-700 dark:bg-rose-900/30 dark:text-rose-200',
    neutral: 'bg-slate-100 text-slate-700 dark:bg-slate-700/50 dark:text-slate-200',
  };

  const confidencePercent = Math.round(confidence * 100);

  return (
    <div className="flex items-center space-x-2">
      <span className={`px-2.5 py-0.5 rounded-full text-[11px] font-semibold uppercase tracking-wide ${colors[sentiment]}`}>
        {sentiment}
      </span>
      <span className="text-[11px] text-gray-500 dark:text-gray-400">{confidencePercent}% confidence</span>
    </div>
  );
};

const RecommendationBadge: React.FC<{ recommendation: string }> = ({ recommendation }) => {
  const normalized = recommendation.trim().toUpperCase();
  const styles: Record<string, string> = {
    BUY: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-200',
    HOLD: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-200',
    SELL: 'bg-rose-100 text-rose-700 dark:bg-rose-900/30 dark:text-rose-200',
  };
  const className = styles[normalized] ?? 'bg-slate-100 text-slate-700 dark:bg-slate-700/50 dark:text-slate-200';

  return (
    <span className={`px-2.5 py-0.5 rounded-full text-[11px] font-semibold uppercase tracking-wide ${className}`}>
      {normalized}
    </span>
  );
};

/* ------------------------------------------------------------------ */
/*  Markdown plugins (shared constant)                                 */
/* ------------------------------------------------------------------ */

const markdownPlugins = [remarkGfm];

/* ------------------------------------------------------------------ */
/*  Agent color map for viewpoint cards                                */
/* ------------------------------------------------------------------ */

const AGENT_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  price_agent:         { bg: 'bg-blue-50 dark:bg-blue-900/20',    text: 'text-blue-700 dark:text-blue-300',    border: 'border-blue-200 dark:border-blue-800' },
  news_agent:          { bg: 'bg-amber-50 dark:bg-amber-900/20',  text: 'text-amber-700 dark:text-amber-300',  border: 'border-amber-200 dark:border-amber-800' },
  technical_agent:     { bg: 'bg-indigo-50 dark:bg-indigo-900/20', text: 'text-indigo-700 dark:text-indigo-300', border: 'border-indigo-200 dark:border-indigo-800' },
  fundamental_agent:   { bg: 'bg-emerald-50 dark:bg-emerald-900/20', text: 'text-emerald-700 dark:text-emerald-300', border: 'border-emerald-200 dark:border-emerald-800' },
  macro_agent:         { bg: 'bg-purple-50 dark:bg-purple-900/20', text: 'text-purple-700 dark:text-purple-300', border: 'border-purple-200 dark:border-purple-800' },
  deep_search_agent:   { bg: 'bg-rose-50 dark:bg-rose-900/20',    text: 'text-rose-700 dark:text-rose-300',    border: 'border-rose-200 dark:border-rose-800' },
};

const DEFAULT_AGENT_COLOR = { bg: 'bg-slate-50 dark:bg-slate-800', text: 'text-slate-700 dark:text-slate-300', border: 'border-slate-200 dark:border-slate-700' };

/* ------------------------------------------------------------------ */
/*  CoreViewpointCard                                                  */
/* ------------------------------------------------------------------ */

const CoreViewpointCard: React.FC<{ viewpoint: CoreViewpoint }> = ({ viewpoint }) => {
  const [expanded, setExpanded] = useState(false);
  const colors = AGENT_COLORS[viewpoint.agent_name] ?? DEFAULT_AGENT_COLOR;
  const hasDetail = viewpoint.detail.length > viewpoint.headline.length + 50;
  const confidencePercent = Math.round(viewpoint.confidence * 100);

  return (
    <div className={`rounded-lg border ${colors.border} ${colors.bg} p-3 transition-all`}>
      {/* Header row: agent badge + confidence */}
      <div className="flex items-center justify-between mb-1.5">
        <span className={`px-2 py-0.5 rounded-full text-[11px] font-semibold ${colors.text} ${colors.bg} border ${colors.border}`}>
          {viewpoint.title}
        </span>
        <span className="text-[11px] text-slate-500 dark:text-slate-400">
          {confidencePercent}%
          {viewpoint.evidence_count > 0 && (
            <span className="ml-1.5 text-slate-400 dark:text-slate-500">
              · {viewpoint.evidence_count} sources
            </span>
          )}
        </span>
      </div>

      {/* Headline */}
      <p className="text-sm font-medium text-slate-800 dark:text-slate-100 leading-relaxed">
        {viewpoint.headline}
      </p>

      {/* Expandable detail */}
      {hasDetail && (
        <>
          {expanded && (
            <div className="mt-2 text-xs text-slate-600 dark:text-slate-300 leading-relaxed whitespace-pre-line">
              {viewpoint.detail}
            </div>
          )}
          <button
            type="button"
            onClick={() => setExpanded(!expanded)}
            className="mt-1.5 flex items-center gap-1 text-[11px] text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 transition-colors"
          >
            {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            {expanded ? '收起' : '展开详情'}
          </button>
        </>
      )}

      {/* Data sources pills */}
      {viewpoint.data_sources.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {viewpoint.data_sources.slice(0, 4).map((src) => (
            <span
              key={src}
              className="px-1.5 py-0.5 rounded text-2xs bg-white/60 dark:bg-slate-900/40 text-slate-500 dark:text-slate-400 border border-slate-200/60 dark:border-slate-700/40"
            >
              {src}
            </span>
          ))}
        </div>
      )}
    </div>
  );
};

/* ------------------------------------------------------------------ */
/*  Shared viewpoints section renderer                                 */
/* ------------------------------------------------------------------ */

const CoreViewpointsSection: React.FC<{
  report: ReportIR;
  sourceSummary: { domain: string; count: number }[];
  sourceItemClassName?: string;
}> = ({ report, sourceSummary, sourceItemClassName }) => {
  const viewpoints = report.core_viewpoints;

  if (viewpoints && viewpoints.length > 0) {
    return (
      <>
        <div className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-300 mb-2">
          核心观点
        </div>
        <div className="space-y-2">
          {viewpoints.map((vp) => (
            <CoreViewpointCard key={vp.agent_name} viewpoint={vp} />
          ))}
        </div>
        {sourceSummary.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2 text-2xs">
            {sourceSummary.map((item) => (
              <span
                key={item.domain}
                className={sourceItemClassName ?? 'px-2 py-0.5 rounded-full border border-slate-200 dark:border-slate-700 bg-white/70 dark:bg-slate-900/60 text-slate-500 dark:text-slate-300'}
              >
                {item.domain} · {item.count}
              </span>
            ))}
          </div>
        )}
      </>
    );
  }

  // Fallback: render summary as markdown blob
  return (
    <>
      <div className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-300 mb-2">
        核心观点
      </div>
      <div className="prose prose-sm dark:prose-invert max-w-none text-slate-700 dark:text-slate-200 leading-relaxed">
        <ReactMarkdown remarkPlugins={markdownPlugins}>{normalizeMarkdown(report.summary)}</ReactMarkdown>
      </div>
      {sourceSummary.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2 text-2xs">
          {sourceSummary.map((item) => (
            <span
              key={item.domain}
              className={sourceItemClassName ?? 'px-2 py-0.5 rounded-full border border-slate-200 dark:border-slate-700 bg-white/70 dark:bg-slate-900/60 text-slate-500 dark:text-slate-300'}
            >
              {item.domain} · {item.count}
            </span>
          ))}
        </div>
      )}
    </>
  );
};

/* ------------------------------------------------------------------ */
/*  ReportHeader                                                       */
/* ------------------------------------------------------------------ */

export interface ReportHeaderProps {
  report: ReportIR;
  formattedDate: string;
  evidenceBadges: { quality: BadgeInfo; freshness: BadgeInfo };
  sourceSummary: { domain: string; count: number }[];
  reportHints: ReportHints;
  warningNode: React.ReactNode;
  /** Render in fullscreen (simplified) mode */
  fullscreen?: boolean;
}

export const ReportHeader: React.FC<ReportHeaderProps> = ({
  report,
  formattedDate,
  evidenceBadges,
  sourceSummary,
  reportHints,
  warningNode,
  fullscreen = false,
}) => {
  if (fullscreen) {
    return (
      <div className="border-b border-slate-200/80 dark:border-slate-700/70 pb-6">
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500 dark:text-slate-400 mb-2">
          <span className="px-2 py-0.5 rounded-full bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-200 font-semibold uppercase tracking-wide">
            Deep Research
          </span>
          <span className="font-mono bg-slate-200/80 dark:bg-slate-700 px-2 py-0.5 rounded text-[11px]">{report.ticker}</span>
          <span>{formattedDate}</span>
        </div>
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white mb-2">{report.title}</h1>
        <div className="flex flex-wrap items-center gap-2">
          <SentimentBadge sentiment={report.sentiment} confidence={report.confidence_score} />
          {report.recommendation && <RecommendationBadge recommendation={report.recommendation} />}
          <span className={`px-2.5 py-0.5 rounded-full text-[11px] font-semibold uppercase tracking-wide ${evidenceBadges.quality.tone}`}>
            {evidenceBadges.quality.label}
          </span>
          <span className={`px-2.5 py-0.5 rounded-full text-[11px] font-semibold uppercase tracking-wide ${evidenceBadges.freshness.tone}`}>
            {evidenceBadges.freshness.label}
          </span>
        </div>
        <div className="mt-4 p-4 bg-slate-50 dark:bg-slate-800 rounded-lg">
          <CoreViewpointsSection
            report={report}
            sourceSummary={sourceSummary}
            sourceItemClassName="px-2 py-0.5 rounded-full border border-slate-200 dark:border-slate-700 bg-white/70 dark:bg-slate-900/60 text-slate-500 dark:text-slate-300"
          />
        </div>
        {warningNode && <div className="mt-4">{warningNode}</div>}
      </div>
    );
  }

  /* Normal (card) mode */
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
        <span className="px-2 py-0.5 rounded-full bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-200 font-semibold uppercase tracking-wide">
          Deep Research
        </span>
        <span className="font-mono bg-slate-200/80 dark:bg-slate-700 px-2 py-0.5 rounded text-[11px]">{report.ticker}</span>
        <span className="text-slate-300 dark:text-slate-600">·</span>
        <span>{formattedDate}</span>
      </div>
      <div>
        <h2 className="text-xl font-semibold text-slate-900 dark:text-white">{report.title}</h2>
        {report.company_name && (
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">{report.company_name}</p>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <SentimentBadge sentiment={report.sentiment} confidence={report.confidence_score} />
        {report.recommendation && <RecommendationBadge recommendation={report.recommendation} />}
        <span className={`px-2.5 py-0.5 rounded-full text-[11px] font-semibold uppercase tracking-wide ${evidenceBadges.quality.tone}`}>
          {evidenceBadges.quality.label}
        </span>
        <span className={`px-2.5 py-0.5 rounded-full text-[11px] font-semibold uppercase tracking-wide ${evidenceBadges.freshness.tone}`}>
          {evidenceBadges.freshness.label}
        </span>
      </div>

      {/* Summary box */}
      <div className="mt-4 rounded-xl border border-slate-200/80 dark:border-slate-700/60 bg-white/70 dark:bg-slate-900/60 p-4">
        <CoreViewpointsSection
          report={report}
          sourceSummary={sourceSummary}
          sourceItemClassName="px-2 py-0.5 rounded-full border border-slate-200 dark:border-slate-700 bg-slate-50/80 dark:bg-slate-800/60 text-slate-500 dark:text-slate-300"
        />

        {(reportHints.is_compare || reportHints.has_conflict) && (
          <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px]">
            {reportHints.is_compare && (
              <span className="px-2 py-0.5 rounded-full bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-200">
                对比报告
              </span>
            )}
            {reportHints.has_conflict && (
              <span className="px-2 py-0.5 rounded-full bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-200">
                存在证据冲突，请重点复核
              </span>
            )}
            {Array.isArray(reportHints.conflict_agents) && reportHints.conflict_agents.length > 0 && (
              <span className="text-2xs text-slate-500 dark:text-slate-400">
                冲突来源：{reportHints.conflict_agents.join(', ')}
              </span>
            )}
          </div>
        )}
      </div>
      {warningNode && <div className="mt-4">{warningNode}</div>}

      {/* Icon */}
      <div className="absolute top-6 right-6 h-12 w-12 rounded-2xl bg-blue-100 dark:bg-blue-900/30 flex items-center justify-center">
        <TrendingUp className="text-blue-600 dark:text-blue-300" size={22} />
      </div>
    </div>
  );
};
