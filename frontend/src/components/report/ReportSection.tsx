import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { normalizeMarkdown } from '../../utils/markdown';
import type { ReportSection as ReportSectionType, ReportContent, Citation } from '../../types/index';
import { ChevronDown, ChevronUp, BarChart2, ExternalLink } from 'lucide-react';
import ReactECharts from 'echarts-for-react';
import { buildChartOption } from './ReportUtils';

const markdownPlugins = [remarkGfm];

/* ------------------------------------------------------------------ */
/*  SectionRenderer                                                    */
/* ------------------------------------------------------------------ */

export interface ReportSectionProps {
  section: ReportSectionType;
  isOpen: boolean;
  isActive: boolean;
  anchorPrefix: string;
  onToggle: () => void;
  citationMap: Map<string, Citation>;
  onCitationJump: (ref: string) => void;
}

export const ReportSection: React.FC<ReportSectionProps> = ({
  section,
  isOpen,
  isActive,
  anchorPrefix,
  onToggle,
  citationMap,
  onCitationJump,
}) => {
  const sectionId = `${anchorPrefix}-section-${section.order}`;
  const agentName = (section as any).agent_name;
  const confidence = (section as any).confidence;
  const dataSources: string[] = (section as any).data_sources || [];
  const hasError = (section as any).error;
  const status = (section as any).status;

  return (
    <div
      id={sectionId}
      data-report-anchor={anchorPrefix}
      data-section-order={section.order}
      className={`border ${hasError ? 'border-amber-300 dark:border-amber-700' : 'border-slate-200 dark:border-slate-700'} rounded-xl overflow-hidden bg-white dark:bg-slate-900 shadow-sm transition-all ${isActive ? 'ring-1 ring-blue-200 dark:ring-blue-500/40' : ''}`}
    >
      <button
        onClick={onToggle}
        className={`w-full flex items-center justify-between px-4 py-3 ${hasError ? 'bg-amber-50/80 dark:bg-amber-900/20' : 'bg-slate-50/80 dark:bg-slate-800/60'} hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors`}
      >
        <div className="flex items-center gap-3">
          <span className={`h-6 w-6 rounded-full ${hasError ? 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300' : 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300'} flex items-center justify-center text-xs font-bold`}>
            {section.order}
          </span>
          <div className="text-left">
            <h3 className="text-sm font-semibold text-slate-900 dark:text-white">{section.title}</h3>
            {agentName && (
              <div className="flex items-center gap-2 mt-0.5">
                <span className="text-2xs px-1.5 py-0.5 rounded bg-slate-200 dark:bg-slate-700 text-slate-600 dark:text-slate-300">
                  {agentName}
                </span>
                {status === 'not_run' && (
                  <span className="text-2xs px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-400">
                    未运行
                  </span>
                )}
                {confidence !== undefined && confidence > 0 && (
                  <span className="text-2xs text-slate-400">
                    {Math.round(confidence * 100)}% 置信度
                  </span>
                )}
                {dataSources.length > 0 && (
                  <span className="text-2xs text-slate-400">
                    · {dataSources.join(', ')}
                  </span>
                )}
              </div>
            )}
          </div>
        </div>
        {isOpen ? <ChevronUp size={16} className="text-slate-500" /> : <ChevronDown size={16} className="text-slate-500" />}
      </button>

      <div
        className={`grid transition-all duration-300 ease-out ${isOpen ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0'}`}
      >
        <div className="overflow-hidden">
          <div className="p-4 bg-white dark:bg-slate-900 space-y-4">
            {section.contents.map((content: ReportContent, idx: number) => {
              const chartTitle = content.metadata?.title || 'Untitled';
              const imageUrl = typeof content.content === 'string' ? content.content : content.content?.url;
              const imageAlt = content.metadata?.title || content.content?.alt || 'Report visual';
              const chartOption = content.type === 'chart' ? buildChartOption(content) : null;
              const citations = content.citation_refs || [];

              return (
                <div key={idx} className="text-sm text-slate-700 dark:text-slate-200">
                  {content.type === 'text' && (
                    <div className="leading-relaxed prose prose-sm prose-slate dark:prose-invert max-w-none">
                      <ReactMarkdown remarkPlugins={markdownPlugins}>{normalizeMarkdown(String(content.content || ''))}</ReactMarkdown>
                    </div>
                  )}

                  {content.type === 'chart' && (
                    <div className="bg-slate-50 dark:bg-slate-800 p-3 rounded-lg border border-slate-200 dark:border-slate-700">
                      {chartOption ? (
                        <ReactECharts
                          option={chartOption}
                          style={{ height: 260, width: '100%' }}
                          notMerge
                          lazyUpdate
                        />
                      ) : (
                        <div className="h-[260px] flex items-center justify-center text-slate-400 flex-col">
                          <BarChart2 size={32} className="mb-2 opacity-60" />
                          <span className="text-xs font-semibold text-slate-500 dark:text-slate-400">
                            Chart: {chartTitle}
                          </span>
                          <span className="text-[11px] text-slate-400 mt-1">Missing chart option data.</span>
                        </div>
                      )}
                    </div>
                  )}

                  {content.type === 'table' && (
                    <div className="overflow-x-auto">
                      <table className="min-w-full divide-y divide-slate-200 dark:divide-slate-700">
                        <thead className="bg-slate-50 dark:bg-slate-800">
                          <tr>
                            {content.content.headers?.map((h: string, i: number) => (
                              <th key={i} className="px-3 py-2 text-left text-[11px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">{h}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody className="bg-white dark:bg-slate-900 divide-y divide-slate-200 dark:divide-slate-700">
                          {content.content.rows?.map((row: string[], rI: number) => (
                            <tr key={rI}>
                              {row.map((cell, cI) => (
                                <td key={cI} className="px-3 py-2 whitespace-nowrap text-xs text-slate-600 dark:text-slate-300">{cell}</td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {content.type === 'image' && imageUrl && (
                    <div className="overflow-hidden rounded-lg border border-slate-200 dark:border-slate-700">
                      <img src={imageUrl} alt={imageAlt} className="w-full h-auto" />
                    </div>
                  )}

                  {citations.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-2">
                      {citations.map((ref) => {
                        const citation = citationMap.get(ref);
                        return (
                          <button
                            key={ref}
                            type="button"
                            onClick={() => onCitationJump(ref)}
                            className="px-2 py-0.5 rounded-full border border-slate-200 dark:border-slate-700 bg-white/70 dark:bg-slate-900 text-[11px] text-slate-500 dark:text-slate-300 hover:border-blue-400 hover:text-blue-600 transition"
                            title={citation?.title || ref}
                          >
                            {citation?.source_id || ref}
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
};
