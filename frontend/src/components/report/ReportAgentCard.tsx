import React, { useMemo, useState } from 'react';
import type { ReportSection, Citation } from '../../types/index';
import { ChevronDown, Check, Copy } from 'lucide-react';
import { EvidencePool } from './ReportCharts';
import { useStore } from '../../store/useStore';

/* ------------------------------------------------------------------ */
/*  Agent detail panel                                                 */
/* ------------------------------------------------------------------ */

export interface ReportAgentCardProps {
  agentDetailSections: ReportSection[];
  expandedSections: Record<string | number, boolean>;
  onToggleSection: (order: number) => void;
}

interface AgentDetailPayload {
  raw_output: any;
  evidence_full: any[];
  trace_full: any[];
  report_input: any;
}

const readSummary = (section: ReportSection): string => {
  const firstText = section.contents.find((content) => content.type === 'text');
  if (!firstText) return '暂无输出';
  return String(firstText.content || '暂无输出');
};

const readDetailPayload = (section: ReportSection): AgentDetailPayload => {
  const firstText = section.contents.find((content) => content.type === 'text');
  const metaPayload = firstText?.metadata?.detail_payload as Partial<AgentDetailPayload> | undefined;
  return {
    raw_output: metaPayload?.raw_output ?? {},
    evidence_full: Array.isArray(metaPayload?.evidence_full) ? metaPayload?.evidence_full : [],
    trace_full: Array.isArray(metaPayload?.trace_full) ? metaPayload?.trace_full : [],
    report_input: metaPayload?.report_input ?? {},
  };
};

const JsonViewer: React.FC<{ label: string; value: any }> = ({ label, value }) => {
  const [copied, setCopied] = useState(false);
  const content = useMemo(() => {
    try {
      return JSON.stringify(value ?? {}, null, 2);
    } catch {
      return String(value ?? '');
    }
  }, [value]);

  return (
    <div className="rounded-lg border border-slate-200/70 dark:border-slate-700/60 overflow-hidden">
      <div className="px-3 py-2 bg-slate-50 dark:bg-slate-800/70 flex items-center justify-between">
        <span className="text-xs font-medium text-slate-700 dark:text-slate-200">{label}</span>
        <button
          type="button"
          className="inline-flex items-center gap-1 text-2xs text-slate-500 hover:text-slate-800 dark:hover:text-slate-200"
          onClick={async () => {
            await navigator.clipboard.writeText(content);
            setCopied(true);
            setTimeout(() => setCopied(false), 1200);
          }}
        >
          {copied ? <Check size={12} className="text-emerald-500" /> : <Copy size={12} />}
          {copied ? '已复制' : '复制'}
        </button>
      </div>
      <pre className="p-3 text-[11px] leading-relaxed overflow-auto max-h-[320px] bg-white dark:bg-slate-900 text-slate-700 dark:text-slate-200 whitespace-pre-wrap break-all">
        {content}
      </pre>
    </div>
  );
};

const EvidenceExcerptList: React.FC<{ evidence: any[] }> = ({ evidence }) => {
  if (!Array.isArray(evidence) || evidence.length === 0) {
    return (
      <div className="rounded-lg border border-slate-200/70 dark:border-slate-700/60 p-3 text-xs text-slate-500 dark:text-slate-400">
        暂无证据摘录
      </div>
    );
  }

  const rows = evidence.slice(0, 8);
  return (
    <div className="rounded-lg border border-slate-200/70 dark:border-slate-700/60 bg-slate-50/60 dark:bg-slate-800/40 p-3 space-y-3">
      {rows.map((item, index) => {
        const sourceId = String(item?.source_id || item?.id || index + 1);
        const title = String(item?.title || item?.source || item?.url || `证据 ${index + 1}`);
        const snippet = String(item?.snippet || item?.summary || item?.content || '').trim();
        const url = String(item?.url || '').trim();
        return (
          <div key={`${sourceId}-${index}`} className="text-xs text-slate-700 dark:text-slate-200">
            <div className="font-semibold text-slate-800 dark:text-slate-100">
              [{sourceId}] {title}
            </div>
            {snippet && <div className="mt-1 leading-relaxed">{snippet.slice(0, 320)}</div>}
            {url && (
              <a
                href={url}
                target="_blank"
                rel="noreferrer"
                className="mt-1 inline-block text-blue-600 dark:text-blue-300 hover:underline break-all"
              >
                {url}
              </a>
            )}
          </div>
        );
      })}
    </div>
  );
};

export const ReportAgentCard: React.FC<ReportAgentCardProps> = ({
  agentDetailSections,
  expandedSections,
  onToggleSection,
}) => {
  const traceViewMode = useStore((state) => state.traceViewMode);
  const isDeveloper = traceViewMode === 'dev';
  const [evidenceExpanded, setEvidenceExpanded] = useState<Record<number, boolean>>({});
  const [debugExpanded, setDebugExpanded] = useState<Record<number, boolean>>({});

  const toggleEvidence = (order: number) => {
    setEvidenceExpanded((prev) => ({ ...prev, [order]: !prev[order] }));
  };

  const toggleDebug = (order: number) => {
    setDebugExpanded((prev) => ({ ...prev, [order]: !prev[order] }));
  };

  if (agentDetailSections.length > 0) {
    return (
      <details className="group rounded-xl border border-slate-200/80 dark:border-slate-700/60 bg-white/70 dark:bg-slate-900/50 overflow-hidden">
        <summary className="px-5 py-3 cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors flex items-center gap-2">
          <ChevronDown size={16} className="text-slate-400 group-open:rotate-180 transition-transform" />
          <span className="text-sm font-semibold text-slate-700 dark:text-slate-200">Agent 分析详情</span>
          <span className="text-2xs text-slate-400 ml-auto">{agentDetailSections.length} 个数据源</span>
        </summary>

        <div className="p-4 pt-0 space-y-3">
          {agentDetailSections.map((section) => {
            const payload = readDetailPayload(section);
            const summary = readSummary(section);
            const isOpen = expandedSections[section.order] ?? true;
            const evidenceCount = payload.evidence_full.length;
            const isEvidenceOpen = evidenceExpanded[section.order] ?? false;
            const isDebugOpen = debugExpanded[section.order] ?? false;

            return (
              <div
                key={`${section.order}-${section.title}`}
                className="border border-slate-200 dark:border-slate-700 rounded-xl overflow-hidden bg-white dark:bg-slate-900 shadow-sm"
              >
                <button
                  type="button"
                  onClick={() => onToggleSection(section.order)}
                  className="w-full flex items-center justify-between px-4 py-3 bg-slate-50/80 dark:bg-slate-800/60 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
                >
                  <div className="flex items-center gap-3">
                    <span className="h-6 w-6 rounded-full bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300 flex items-center justify-center text-xs font-bold">
                      {section.order}
                    </span>
                    <div className="text-left">
                      <div className="text-sm font-semibold text-slate-900 dark:text-white">{section.title}</div>
                      <div className="text-2xs text-slate-500 dark:text-slate-400 mt-0.5">
                        {section.agent_name || 'agent'} · confidence {Math.round((section.confidence || 0) * 100)}%
                      </div>
                    </div>
                  </div>
                  <ChevronDown
                    size={16}
                    className={`text-slate-400 transition-transform ${isOpen ? 'rotate-180' : ''}`}
                  />
                </button>

                {isOpen && (
                  <div className="p-4 space-y-3">
                    <div className="rounded-lg border border-slate-200/70 dark:border-slate-700/60 p-3 bg-slate-50/60 dark:bg-slate-800/40">
                      <div className="text-2xs text-slate-500 dark:text-slate-400 mb-1">Summary</div>
                      <div className="text-xs leading-relaxed text-slate-700 dark:text-slate-200 whitespace-pre-wrap">
                        {summary}
                      </div>
                    </div>

                    <div className="flex items-center gap-3 text-2xs">
                      <button
                        type="button"
                        onClick={() => toggleEvidence(section.order)}
                        disabled={evidenceCount === 0}
                        className={`underline-offset-2 hover:underline ${
                          evidenceCount === 0
                            ? 'text-slate-400 cursor-not-allowed'
                            : 'text-slate-600 dark:text-slate-300'
                        }`}
                      >
                        {isEvidenceOpen ? '收起依据' : `查看依据 (${evidenceCount})`}
                      </button>

                      {isDeveloper && (
                        <button
                          type="button"
                          onClick={() => toggleDebug(section.order)}
                          className="text-indigo-600 dark:text-indigo-300 underline-offset-2 hover:underline"
                        >
                          {isDebugOpen ? '收起 Debug（仅开发者）' : 'Debug（仅开发者）'}
                        </button>
                      )}
                    </div>

                    {isEvidenceOpen && <EvidenceExcerptList evidence={payload.evidence_full} />}

                    {isDeveloper && isDebugOpen && (
                      <div className="space-y-3">
                        <JsonViewer label="整合输入（给研报生成器）" value={payload.report_input} />
                        <details className="rounded-lg border border-slate-200/70 dark:border-slate-700/60 overflow-hidden">
                          <summary className="px-3 py-2 cursor-pointer bg-slate-50 dark:bg-slate-800/70 text-xs font-medium text-slate-700 dark:text-slate-200">
                            原始输出（采集/trace）
                          </summary>
                          <div className="p-3 space-y-3 bg-white dark:bg-slate-900 border-t border-slate-200/70 dark:border-slate-700/60">
                            <JsonViewer label="Raw Output" value={payload.raw_output} />
                            <JsonViewer label="Trace Full" value={payload.trace_full} />
                          </div>
                        </details>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
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
    <details
      className="group rounded-xl border border-slate-200/80 dark:border-slate-700/60 bg-white/70 dark:bg-slate-900/50 overflow-hidden"
      open
    >
      <summary className="px-5 py-3 cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors flex items-center gap-2">
        <ChevronDown size={16} className="text-slate-400 group-open:rotate-180 transition-transform" />
        <span className="text-sm font-semibold text-slate-700 dark:text-slate-200">证据池</span>
        <span className="text-2xs text-slate-400 ml-auto">{citations.length} 条来源</span>
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

