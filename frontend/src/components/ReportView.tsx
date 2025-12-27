import React, { useState } from 'react';
import { ReportIR, ReportSection, ReportContent, Citation, Sentiment } from '../types';
import { ChevronDown, ChevronUp, ExternalLink, BarChart2, TrendingUp, AlertTriangle } from 'lucide-react';
import ReactECharts from 'echarts-for-react';

interface ReportViewProps {
  report: ReportIR;
}

const SentimentBadge: React.FC<{ sentiment: Sentiment; confidence: number }> = ({ sentiment, confidence }) => {
  const colors = {
    bullish: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300',
    bearish: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300',
    neutral: 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300',
  };

  const confidencePercent = Math.round(confidence * 100);

  return (
    <div className="flex items-center space-x-2">
      <span className={`px-2.5 py-0.5 rounded-full text-xs font-medium uppercase ${colors[sentiment]}`}>
        {sentiment}
      </span>
      <div className="flex items-center space-x-1 text-xs text-gray-500 dark:text-gray-400">
        <span>Confidence:</span>
        <div className="w-16 h-1.5 bg-gray-200 rounded-full overflow-hidden dark:bg-gray-700">
          <div
            className="h-full bg-blue-500 rounded-full"
            style={{ width: `${confidencePercent}%` }}
          />
        </div>
        <span>{confidencePercent}%</span>
      </div>
    </div>
  );
};

const SectionRenderer: React.FC<{ section: ReportSection; isOpen: boolean; onToggle: () => void }> = ({ section, isOpen, onToggle }) => {
  return (
    <div className="border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden mb-4">
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between p-4 bg-gray-50 dark:bg-gray-800/50 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
      >
        <h3 className="text-sm font-semibold text-gray-900 dark:text-white flex items-center">
          <span className="mr-2 text-blue-500">{section.order}.</span>
          {section.title}
        </h3>
        {isOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
      </button>

      {isOpen && (
        <div className="p-4 bg-white dark:bg-gray-900 space-y-4">
          {section.contents.map((content, idx) => (
            <div key={idx} className="text-sm text-gray-700 dark:text-gray-300">
              {content.type === 'text' && (
                <p className="leading-relaxed whitespace-pre-wrap">{content.content}</p>
              )}

              {content.type === 'chart' && (
                 <div className="bg-white dark:bg-gray-800 p-2 rounded border border-gray-100 dark:border-gray-700 h-64">
                   {/* Placeholder for real ECharts integration based on metadata */}
                   <div className="h-full flex items-center justify-center text-gray-400 flex-col">
                     <BarChart2 size={32} className="mb-2 opacity-50" />
                     <span className="text-xs">Chart: {content.metadata?.title || 'Untitled'}</span>
                   </div>
                 </div>
              )}

              {content.type === 'table' && (
                <div className="overflow-x-auto">
                  <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
                    <thead className="bg-gray-50 dark:bg-gray-800">
                      <tr>
                        {content.content.headers?.map((h: string, i: number) => (
                          <th key={i} className="px-3 py-2 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="bg-white dark:bg-gray-900 divide-y divide-gray-200 dark:divide-gray-700">
                      {content.content.rows?.map((row: string[], rI: number) => (
                        <tr key={rI}>
                          {row.map((cell, cI) => (
                            <td key={cI} className="px-3 py-2 whitespace-nowrap text-xs text-gray-500 dark:text-gray-400">{cell}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

const CitationList: React.FC<{ citations: Citation[] }> = ({ citations }) => {
  if (!citations || citations.length === 0) return null;

  return (
    <div className="mt-6 pt-4 border-t border-gray-200 dark:border-gray-700">
      <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">References</h4>
      <div className="grid grid-cols-1 gap-2">
        {citations.map((cit) => (
          <a
            key={cit.source_id}
            href={cit.url}
            target="_blank"
            rel="noopener noreferrer"
            className="group flex items-start p-2 rounded hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors text-xs"
          >
            <ExternalLink size={12} className="mt-0.5 mr-2 text-gray-400 group-hover:text-blue-500 flex-shrink-0" />
            <div>
              <div className="font-medium text-blue-600 dark:text-blue-400 group-hover:underline">
                {cit.title}
              </div>
              <div className="text-gray-500 dark:text-gray-400 mt-0.5 line-clamp-1">
                {cit.snippet}
              </div>
              {cit.published_date && (
                <div className="text-gray-400 text-[10px] mt-1">{cit.published_date}</div>
              )}
            </div>
          </a>
        ))}
      </div>
    </div>
  );
};

export const ReportView: React.FC<ReportViewProps> = ({ report }) => {
  // 默认展开所有章节
  const [expandedSections, setExpandedSections] = useState<Record<number, boolean>>(
    report.sections.reduce((acc, sec) => ({ ...acc, [sec.order]: true }), {})
  );

  const toggleSection = (order: number) => {
    setExpandedSections(prev => ({ ...prev, [order]: !prev[order] }));
  };

  return (
    <div className="bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden max-w-4xl mx-auto my-4">
      {/* Header */}
      <div className="p-6 border-b border-gray-200 dark:border-gray-700 bg-gradient-to-r from-blue-50 to-white dark:from-gray-800 dark:to-gray-900">
        <div className="flex justify-between items-start">
          <div>
            <div className="flex items-center space-x-2 text-sm text-gray-500 mb-1">
              <span className="font-mono bg-gray-200 dark:bg-gray-700 px-1.5 py-0.5 rounded text-xs">{report.ticker}</span>
              <span>•</span>
              <span>{new Date(report.generated_at).toLocaleDateString()}</span>
            </div>
            <h2 className="text-xl font-bold text-gray-900 dark:text-white mb-2">{report.title}</h2>
            <SentimentBadge sentiment={report.sentiment} confidence={report.confidence_score} />
          </div>
          <div className="bg-blue-100 dark:bg-blue-900/20 p-2 rounded-lg">
            <TrendingUp className="text-blue-600 dark:text-blue-400" size={24} />
          </div>
        </div>

        {/* Summary */}
        <div className="mt-4 p-3 bg-white/60 dark:bg-gray-800/60 rounded-lg border border-gray-100 dark:border-gray-700 backdrop-blur-sm">
          <p className="text-sm text-gray-700 dark:text-gray-300 italic">
            "{report.summary}"
          </p>
        </div>
      </div>

      {/* Content */}
      <div className="p-6 bg-gray-50/50 dark:bg-gray-900/50">
        {/* Risks Warning if present */}
        {report.risks && report.risks.length > 0 && (
          <div className="mb-6 p-3 bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-800 rounded-lg">
            <div className="flex items-center mb-2">
              <AlertTriangle size={14} className="text-red-500 mr-2" />
              <span className="text-xs font-bold text-red-700 dark:text-red-400 uppercase">Key Risks</span>
            </div>
            <ul className="list-disc list-inside text-xs text-red-600 dark:text-red-300 space-y-1">
              {report.risks.map((risk, i) => (
                <li key={i}>{risk}</li>
              ))}
            </ul>
          </div>
        )}

        {/* Sections */}
        <div className="space-y-4">
          {report.sections.map((section) => (
            <SectionRenderer
              key={section.order}
              section={section}
              isOpen={!!expandedSections[section.order]}
              onToggle={() => toggleSection(section.order)}
            />
          ))}
        </div>

        {/* Citations */}
        <CitationList citations={report.citations} />
      </div>

      {/* Footer */}
      <div className="px-6 py-3 bg-gray-50 dark:bg-gray-800 border-t border-gray-200 dark:border-gray-700 text-[10px] text-gray-400 flex justify-between">
        <span>Generated by FinSight AI • Deep Research Engine</span>
        <span>ID: {report.report_id}</span>
      </div>
    </div>
  );
};
