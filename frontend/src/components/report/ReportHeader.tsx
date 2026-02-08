import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { normalizeMarkdown } from '../../utils/markdown';
import type { ReportIR, Sentiment } from '../../types/index';
import { TrendingUp } from 'lucide-react';
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
                  className="px-2 py-0.5 rounded-full border border-slate-200 dark:border-slate-700 bg-white/70 dark:bg-slate-900/60 text-slate-500 dark:text-slate-300"
                >
                  {item.domain} · {item.count}
                </span>
              ))}
            </div>
          )}
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
                className="px-2 py-0.5 rounded-full border border-slate-200 dark:border-slate-700 bg-slate-50/80 dark:bg-slate-800/60 text-slate-500 dark:text-slate-300"
              >
                {item.domain} · {item.count}
              </span>
            ))}
          </div>
        )}

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
