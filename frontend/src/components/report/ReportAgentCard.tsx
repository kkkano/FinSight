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
    <div className="rounded-lg border border-fin-border overflow-hidden">
      <div className="px-3 py-2 bg-fin-bg-secondary flex items-center justify-between">
        <span className="text-xs font-medium text-fin-text">{label}</span>
        <button
          type="button"
          className="inline-flex items-center gap-1 text-2xs text-fin-text-secondary hover:text-fin-text"
          onClick={async () => {
            await navigator.clipboard.writeText(content);
            setCopied(true);
            setTimeout(() => setCopied(false), 1200);
          }}
        >
          {copied ? <Check size={12} className="text-fin-success" /> : <Copy size={12} />}
          {copied ? '已复制' : '复制'}
        </button>
      </div>
      <pre className="p-3 text-[11px] leading-relaxed overflow-auto max-h-[320px] bg-fin-card text-fin-text whitespace-pre-wrap break-all">
        {content}
      </pre>
    </div>
  );
};

const EvidenceExcerptList: React.FC<{ evidence: any[] }> = ({ evidence }) => {
  if (!Array.isArray(evidence) || evidence.length === 0) {
    return (
      <div className="rounded-lg border border-fin-border p-3 text-xs text-fin-text-secondary">
        暂无证据摘录
      </div>
    );
  }

  const rows = evidence.slice(0, 8);
  return (
    <div className="rounded-lg border border-fin-border bg-fin-bg-secondary p-3 space-y-3">
      {rows.map((item, index) => {
        const sourceId = String(item?.source_id || item?.id || index + 1);
        const title = String(item?.title || item?.source || item?.url || `证据 ${index + 1}`);
        const snippet = String(item?.snippet || item?.summary || item?.content || '').trim();
        const url = String(item?.url || '').trim();
        return (
          <div key={`${sourceId}-${index}`} className="text-xs text-fin-text">
            <div className="font-semibold text-fin-text">
              [{sourceId}] {title}
            </div>
            {snippet && <div className="mt-1 leading-relaxed">{snippet.slice(0, 320)}</div>}
            {url && (
              <a
                href={url}
                target="_blank"
                rel="noreferrer"
                className="mt-1 inline-block text-fin-primary hover:underline break-all"
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
      <details className="group rounded-xl border border-fin-border bg-fin-card overflow-hidden">
        <summary className="px-5 py-3 cursor-pointer hover:bg-fin-hover transition-colors flex items-center gap-2">
          <ChevronDown size={16} className="text-fin-muted group-open:rotate-180 transition-transform" />
          <span className="text-sm font-semibold text-fin-text">Agent 分析详情</span>
          <span className="text-2xs text-fin-muted ml-auto">{agentDetailSections.length} 个数据源</span>
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
                className="border border-fin-border rounded-xl overflow-hidden bg-fin-card shadow-sm"
              >
                <button
                  type="button"
                  onClick={() => onToggleSection(section.order)}
                  className="w-full flex items-center justify-between px-4 py-3 bg-fin-bg-secondary hover:bg-fin-hover transition-colors"
                >
                  <div className="flex items-center gap-3">
                    <span className="h-6 w-6 rounded-full bg-fin-primary/15 text-fin-primary flex items-center justify-center text-xs font-bold">
                      {section.order}
                    </span>
                    <div className="text-left">
                      <div className="text-sm font-semibold text-fin-text">{section.title}</div>
                      <div className="text-2xs text-fin-text-secondary mt-0.5">
                        {section.agent_name || 'agent'} · confidence {Math.round((section.confidence || 0) * 100)}%
                      </div>
                    </div>
                  </div>
                  <ChevronDown
                    size={16}
                    className={`text-fin-muted transition-transform ${isOpen ? 'rotate-180' : ''}`}
                  />
                </button>

                {isOpen && (
                  <div className="p-4 space-y-3">
                    <div className="rounded-lg border border-fin-border p-3 bg-fin-bg-secondary">
                      <div className="text-2xs text-fin-text-secondary mb-1">Summary</div>
                      <div className="text-xs leading-relaxed text-fin-text whitespace-pre-wrap">
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
                            ? 'text-fin-muted cursor-not-allowed'
                            : 'text-fin-text-secondary'
                        }`}
                      >
                        {isEvidenceOpen ? '收起依据' : `查看依据 (${evidenceCount})`}
                      </button>

                      {isDeveloper && (
                        <button
                          type="button"
                          onClick={() => toggleDebug(section.order)}
                          className="text-fin-primary underline-offset-2 hover:underline"
                        >
                          {isDebugOpen ? '收起 Debug（仅开发者）' : 'Debug（仅开发者）'}
                        </button>
                      )}
                    </div>

                    {isEvidenceOpen && <EvidenceExcerptList evidence={payload.evidence_full} />}

                    {isDeveloper && isDebugOpen && (
                      <div className="space-y-3">
                        <JsonViewer label="整合输入（给研报生成器）" value={payload.report_input} />
                        <details className="rounded-lg border border-fin-border overflow-hidden">
                          <summary className="px-3 py-2 cursor-pointer bg-fin-bg-secondary text-xs font-medium text-fin-text">
                            原始输出（采集/trace）
                          </summary>
                          <div className="p-3 space-y-3 bg-fin-card border-t border-fin-border">
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
    <div className="rounded-xl border border-fin-border bg-fin-card overflow-hidden">
      <div className="px-5 py-3 text-sm font-semibold text-fin-text border-b border-fin-border">
        Agent 分析详情
      </div>
      <div className="px-5 py-4 text-xs text-fin-muted">暂无 agent 分析</div>
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
      className="group rounded-xl border border-fin-border bg-fin-card overflow-hidden"
      open
    >
      <summary className="px-5 py-3 cursor-pointer hover:bg-fin-hover transition-colors flex items-center gap-2">
        <ChevronDown size={16} className="text-fin-muted group-open:rotate-180 transition-transform" />
        <span className="text-sm font-semibold text-fin-text">证据池</span>
        <span className="text-2xs text-fin-muted ml-auto">{citations.length} 条来源</span>
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
