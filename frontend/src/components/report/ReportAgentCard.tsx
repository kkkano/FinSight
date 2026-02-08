import React from 'react';
import type { ReportSection, Citation } from '../../types/index';
import { ChevronDown } from 'lucide-react';
import { ReportSection as SectionRenderer } from './ReportSection';
import { EvidencePool } from './ReportCharts';

/* ------------------------------------------------------------------ */
/*  Agent detail panel (collapsible details/summary)                   */
/* ------------------------------------------------------------------ */

export interface ReportAgentCardProps {
  agentDetailSections: ReportSection[];
  expandedSections: Record<string | number, boolean>;
  activeSection: number | null;
  anchorPrefix: string;
  citationMap: Map<string, Citation>;
  onToggleSection: (order: number) => void;
  onCitationJump: (ref: string) => void;
}

export const ReportAgentCard: React.FC<ReportAgentCardProps> = ({
  agentDetailSections,
  expandedSections,
  activeSection,
  anchorPrefix,
  citationMap,
  onToggleSection,
  onCitationJump,
}) => {
  if (agentDetailSections.length > 0) {
    return (
      <details className="group rounded-xl border border-slate-200/80 dark:border-slate-700/60 bg-white/70 dark:bg-slate-900/50 overflow-hidden">
        <summary className="px-5 py-3 cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors flex items-center gap-2">
          <ChevronDown size={16} className="text-slate-400 group-open:rotate-180 transition-transform" />
          <span className="text-sm font-semibold text-slate-700 dark:text-slate-200">
            Agent 分析详情
          </span>
          <span className="text-2xs text-slate-400 ml-auto">
            {agentDetailSections.length} 个数据源
          </span>
        </summary>
        <div className="p-4 pt-0 space-y-3">
          {agentDetailSections.map((section) => (
            <SectionRenderer
              key={`${section.order}-${section.title}`}
              section={section}
              isOpen={expandedSections[section.order] ?? true}
              isActive={activeSection === section.order}
              anchorPrefix={anchorPrefix}
              onToggle={() => onToggleSection(section.order)}
              citationMap={citationMap}
              onCitationJump={onCitationJump}
            />
          ))}
        </div>
      </details>
    );
  }

  return (
    <div className="rounded-xl border border-slate-200/80 dark:border-slate-700/60 bg-white/70 dark:bg-slate-900/50 overflow-hidden">
      <div className="px-5 py-3 text-sm font-semibold text-slate-700 dark:text-slate-200 border-b border-slate-200/70 dark:border-slate-700/60">
        Agent 分析详情
      </div>
      <div className="px-5 py-4 text-xs text-slate-400">暂无 agent 分析</div>
    </div>
  );
};

/* ------------------------------------------------------------------ */
/*  Evidence pool collapsible wrapper                                  */
/* ------------------------------------------------------------------ */

export interface ReportEvidencePoolProps {
  citations: Citation[];
  sourceSummary: { domain: string; count: number }[];
  anchorPrefix: string;
  activeCitation: string | null;
  onSelectCitation: (ref: string) => void;
  onJumpToCitation: (ref: string) => void;
}

export const ReportEvidencePoolSection: React.FC<ReportEvidencePoolProps> = ({
  citations,
  sourceSummary,
  anchorPrefix,
  activeCitation,
  onSelectCitation,
  onJumpToCitation,
}) => {
  if (!citations || citations.length === 0) return null;

  return (
    <details className="group rounded-xl border border-slate-200/80 dark:border-slate-700/60 bg-white/70 dark:bg-slate-900/50 overflow-hidden" open>
      <summary className="px-5 py-3 cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors flex items-center gap-2">
        <ChevronDown size={16} className="text-slate-400 group-open:rotate-180 transition-transform" />
        <span className="text-sm font-semibold text-slate-700 dark:text-slate-200">证据池</span>
        <span className="text-2xs text-slate-400 ml-auto">
          {citations.length} 条来源
        </span>
      </summary>
      <div className="p-4 pt-0">
        <EvidencePool
          citations={citations}
          sourceSummary={sourceSummary}
          anchorPrefix={anchorPrefix}
          activeCitation={activeCitation}
          onSelect={onSelectCitation}
          onJump={onJumpToCitation}
          frameless
        />
      </div>
    </details>
  );
};
