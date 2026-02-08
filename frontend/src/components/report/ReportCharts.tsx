import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { normalizeMarkdown } from '../../utils/markdown';
import type { ReportIR, Citation } from '../../types/index';
import { ChevronDown, ChevronUp, ExternalLink, AlertTriangle, BarChart2, TrendingUp } from 'lucide-react';
import { countContentChars } from './ReportUtils';

const markdownPlugins = [remarkGfm];

/* ------------------------------------------------------------------ */
/*  ConfidenceMeter                                                    */
/* ------------------------------------------------------------------ */

export const ConfidenceMeter: React.FC<{ score: number }> = ({ score }) => {
  const percent = Math.min(100, Math.max(0, Math.round(score * 100)));
  const level = percent >= 80 ? '\u9ad8' : percent >= 60 ? '\u4e2d' : '\u4f4e';
  const levelColor = percent >= 80 ? 'text-emerald-600 dark:text-emerald-400' : percent >= 60 ? 'text-blue-600 dark:text-blue-400' : 'text-amber-600 dark:text-amber-400';

  return (
    <div className="rounded-xl border border-slate-200/80 dark:border-slate-700/60 bg-white/80 dark:bg-slate-900/60 p-4">
      <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400 mb-2">
        <span className="font-semibold uppercase tracking-wider">AI Confidence</span>
        <span className="text-slate-700 dark:text-slate-200 font-semibold">{percent}%</span>
      </div>
      <div className="h-2 rounded-full bg-slate-200 dark:bg-slate-700 overflow-hidden">
        <div
          className="h-full rounded-full bg-gradient-to-r from-emerald-400 via-blue-500 to-indigo-500"
          style={{ width: `${percent}%` }}
        />
      </div>
      <div className="mt-2 text-2xs text-slate-400 dark:text-slate-500">
        <span className={`font-medium ${levelColor}`}>{level}置信度</span>
        <span className="mx-1">·</span>
        <span>综合 Price/News/Technical 等多源 Agent 分析结果</span>
      </div>
    </div>
  );
};

/* ------------------------------------------------------------------ */
/*  AgentStatusGrid                                                    */
/* ------------------------------------------------------------------ */

export interface AgentStatusGridProps {
  report: ReportIR;
}

export const AgentStatusGrid: React.FC<AgentStatusGridProps> = ({ report }) => {
  const agentStatus = (report as any).agent_status;
  if (!agentStatus) return null;

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-3">
      {Object.entries(agentStatus).map(([key, status]: [string, any]) => {
        const isSuccess = status.status === 'success';
        const isSkipped = status.status === 'not_run';
        const confidence = typeof status.confidence === 'number' ? status.confidence : 0;
        const qualityScore = typeof status?.evidence_quality?.overall_score === 'number'
          ? status.evidence_quality.overall_score
          : null;
        const qualityLabel = qualityScore === null ? 'EQ N/A' : `EQ ${Math.round(qualityScore * 100)}%`;
        const qualityTone = qualityScore === null
          ? 'bg-slate-100 text-slate-600 dark:bg-slate-700/50 dark:text-slate-300'
          : qualityScore >= 0.75
            ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-200'
            : qualityScore >= 0.55
              ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-200'
              : 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-200';
        const skipLabel = status.escalation_not_needed
          ? 'Escalation skipped'
          : (status.skipped_reason ? `Skip: ${status.skipped_reason}` : null);

        return (
          <div
            key={key}
            className={`px-2 py-1.5 rounded-lg text-2xs ${isSuccess ? 'bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-300' : isSkipped ? 'bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300' : 'bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-300'}`}
          >
            <div className="font-medium capitalize">{key}</div>
            <div className="flex items-center gap-1">
              <span className={`w-1.5 h-1.5 rounded-full ${isSuccess ? 'bg-emerald-500' : isSkipped ? 'bg-blue-500' : 'bg-amber-500'}`}></span>
              {isSuccess ? `${Math.round(confidence * 100)}%` : isSkipped ? 'Skipped' : 'Failed'}
            </div>
            <div className="mt-1 flex flex-wrap gap-1">
              <span className={`px-1.5 py-0.5 rounded ${qualityTone}`}>{qualityLabel}</span>
              {skipLabel && (
                <span className="px-1.5 py-0.5 rounded bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-200">
                  {skipLabel}
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
};

/* ------------------------------------------------------------------ */
/*  RiskCatalystMetrics  (3-column grid)                               */
/* ------------------------------------------------------------------ */

export interface RiskCatalystMetricsProps {
  risks: string[];
  catalystItems: string[];
  metricItems: { label: string; value: string }[];
}

export const RiskCatalystMetrics: React.FC<RiskCatalystMetricsProps> = ({ risks, catalystItems, metricItems }) => (
  <div className="mt-4 grid gap-3 grid-cols-1 md:grid-cols-3">
    <div className="rounded-xl border border-rose-200/70 bg-rose-50/70 dark:border-rose-800/60 dark:bg-rose-900/20 p-3">
      <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-300 mb-2">
        <AlertTriangle size={12} className="text-rose-500" />
        风险提示
      </div>
      <div className="flex flex-wrap gap-1.5">
        {(risks || []).map((risk, idx) => (
          <span key={idx} className="text-[11px] px-2 py-0.5 rounded-full bg-white/60 dark:bg-slate-800/60 text-slate-600 dark:text-slate-300">
            {risk}
          </span>
        ))}
        {(!risks || risks.length === 0) && (
          <span className="text-[11px] text-slate-400">暂无</span>
        )}
      </div>
    </div>
    <div className="rounded-xl border border-emerald-200/70 bg-emerald-50/70 dark:border-emerald-800/60 dark:bg-emerald-900/20 p-3">
      <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-300 mb-2">
        <TrendingUp size={12} className="text-emerald-500" />
        催化剂
      </div>
      <div className="flex flex-wrap gap-1.5">
        {catalystItems.map((item, idx) => (
          <span key={idx} className="text-[11px] px-2 py-0.5 rounded-full bg-white/60 dark:bg-slate-800/60 text-slate-600 dark:text-slate-300">
            {item.length > 30 ? item.substring(0, 30) + '...' : item}
          </span>
        ))}
        {catalystItems.length === 0 && (
          <span className="text-[11px] text-slate-400">暂无</span>
        )}
      </div>
    </div>
    <div className="rounded-xl border border-slate-200/80 dark:border-slate-700/60 bg-white/80 dark:bg-slate-900/60 p-3">
      <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-300 mb-2">
        <BarChart2 size={12} />
        核心指标
      </div>
      <div className="flex flex-wrap gap-2">
        {metricItems.map((metric) => (
          <div key={`${metric.label}-${metric.value}`} className="text-[11px] px-2 py-1 rounded bg-slate-100 dark:bg-slate-800">
            <span className="text-slate-500 dark:text-slate-400">{metric.label}:</span>{' '}
            <span className="font-medium text-slate-700 dark:text-slate-200">{metric.value}</span>
          </div>
        ))}
        {metricItems.length === 0 && (
          <span className="text-[11px] text-slate-400">暂无</span>
        )}
      </div>
    </div>
  </div>
);

/* ------------------------------------------------------------------ */
/*  SynthesisReportBlock                                               */
/* ------------------------------------------------------------------ */

export interface SynthesisReportBlockProps {
  synthesisReport: string;
  isExpanded: boolean;
  onToggle: () => void;
  onExpand: () => void;
  onCollapse: () => void;
}

export const SynthesisReportBlock: React.FC<SynthesisReportBlockProps> = ({
  synthesisReport,
  isExpanded,
  onToggle,
  onExpand,
  onCollapse,
}) => {
  if (!synthesisReport) return null;

  return (
    <div className="rounded-xl border border-blue-200/80 dark:border-blue-700/60 bg-white/90 dark:bg-slate-900/70 overflow-hidden">
      <div className="px-5 py-3 border-b border-blue-200/60 dark:border-blue-700/40 bg-gradient-to-r from-blue-50 to-indigo-50 dark:from-blue-900/20 dark:to-indigo-900/20">
        <h3 className="text-sm font-semibold text-blue-800 dark:text-blue-200 flex items-center gap-2">
          <span className="text-base">📋</span>
          综合研究报告
          <span className="text-2xs font-normal text-blue-600 dark:text-blue-400 ml-auto">
            {countContentChars(synthesisReport || '')} 字
          </span>
          <button
            onClick={onToggle}
            className="ml-2 p-1 hover:bg-blue-100 dark:hover:bg-blue-900/30 rounded transition-colors"
          >
            {isExpanded ? <ChevronUp size={14} className="text-blue-600" /> : <ChevronDown size={14} className="text-blue-600" />}
          </button>
        </h3>
      </div>

      <div className="relative">
        <div
          className={`p-5 transition-all duration-300 ease-in-out ${isExpanded ? '' : 'max-h-[300px] overflow-hidden'}`}
        >
          <div className="prose prose-sm dark:prose-invert max-w-none text-slate-700 dark:text-slate-200 leading-relaxed">
            <ReactMarkdown remarkPlugins={markdownPlugins}>{normalizeMarkdown(synthesisReport)}</ReactMarkdown>
          </div>
        </div>

        {!isExpanded && (
          <div className="absolute bottom-0 left-0 right-0 h-24 bg-gradient-to-t from-white dark:from-slate-900 to-transparent flex items-end justify-center pb-4">
            <button
              onClick={onExpand}
              className="px-4 py-2 bg-blue-50 hover:bg-blue-100 dark:bg-blue-900/30 dark:hover:bg-blue-800/40 text-blue-600 dark:text-blue-300 rounded-full text-xs font-semibold shadow-sm border border-blue-100 dark:border-blue-800/50 flex items-center gap-2 transition-all hover:scale-105 active:scale-95"
            >
              <ChevronDown size={14} />
              展开完整报告
            </button>
          </div>
        )}
        {isExpanded && (
          <div className="flex justify-center pb-4 pt-2 border-t border-slate-100 dark:border-slate-800/50 mt-2">
            <button
              onClick={onCollapse}
              className="text-xs text-slate-400 hover:text-blue-600 dark:hover:text-blue-400 flex items-center gap-1 transition-colors"
            >
              <ChevronUp size={12} />
              收起报告
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

/* ------------------------------------------------------------------ */
/*  EvidencePool                                                       */
/* ------------------------------------------------------------------ */

export interface EvidencePoolProps {
  citations: Citation[];
  sourceSummary: { domain: string; count: number }[];
  anchorPrefix: string;
  activeCitation: string | null;
  onSelect: (ref: string) => void;
  onJump: (ref: string) => void;
  frameless?: boolean;
  className?: string;
}

export const EvidencePool: React.FC<EvidencePoolProps> = ({
  citations,
  sourceSummary,
  anchorPrefix,
  activeCitation,
  onSelect,
  onJump,
  frameless = false,
  className = '',
}) => {
  if (!citations || citations.length === 0) return null;

  return (
    <div className={`${frameless ? '' : 'rounded-xl border border-slate-200/80 dark:border-slate-700/60 bg-white/80 dark:bg-slate-900/60'} p-4 space-y-3 ${className}`}>
      <div className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-300">
        证据池
      </div>
      {sourceSummary.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {sourceSummary.map((item) => (
            <span
              key={item.domain}
              className="px-2 py-0.5 rounded-full border border-slate-200 dark:border-slate-700 text-2xs text-slate-500 dark:text-slate-300"
            >
              {item.domain} · {item.count}
            </span>
          ))}
        </div>
      )}
      <div className="space-y-2">
        {citations.map((cit) => {
          const citationId = `${anchorPrefix}-citation-${cit.source_id}`;
          const isActive = activeCitation === cit.source_id;
          const confidencePercent = typeof cit.confidence === 'number' ? Math.round(cit.confidence * 100) : null;
          const freshnessHours = typeof cit.freshness_hours === 'number' ? Math.round(cit.freshness_hours) : null;
          const confidenceTone =
            confidencePercent === null
              ? ''
              : confidencePercent >= 80
                ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-200'
                : confidencePercent >= 60
                  ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-200'
                  : 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-200';
          return (
            <div
              key={cit.source_id}
              id={citationId}
              className={`rounded-lg border ${isActive ? 'border-blue-200 bg-blue-50/40 dark:bg-blue-900/20' : 'border-transparent'}`}
            >
              <button
                type="button"
                onClick={() => {
                  onSelect(cit.source_id);
                  onJump(cit.source_id);
                }}
                className="w-full text-left flex items-start gap-2 p-2 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors text-xs"
              >
                <ExternalLink size={12} className="mt-0.5 text-slate-400 flex-shrink-0" />
                <div>
                  <div className="font-medium text-blue-600 dark:text-blue-400">
                    {cit.title}
                  </div>
                  <div className="text-slate-500 dark:text-slate-400 mt-0.5 line-clamp-2">
                    {cit.snippet}
                  </div>
                  {cit.published_date && (
                    <div className="text-slate-400 text-2xs mt-1">{cit.published_date}</div>
                  )}
                  {(confidencePercent !== null || freshnessHours !== null) && (
                    <div className="mt-1 flex flex-wrap gap-1.5 text-2xs">
                      {confidencePercent !== null && (
                        <span className={`px-1.5 py-0.5 rounded-full ${confidenceTone}`}>
                          Confidence {confidencePercent}%
                        </span>
                      )}
                      {freshnessHours !== null && (
                        <span className="px-1.5 py-0.5 rounded-full bg-slate-100 text-slate-600 dark:bg-slate-700/60 dark:text-slate-200">
                          Freshness {freshnessHours}h
                        </span>
                      )}
                    </div>
                  )}
                </div>
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
};
