import React from 'react';
import { ChevronDown, ExternalLink, FileSearch } from 'lucide-react';

import type { EvidenceLedger, ResearchClaim, SourceRef } from '../../types/index';
import { SourceTrustBadge } from '../source/SourceTrustBadge';

export interface EvidenceLedgerPanelProps {
  ledger?: EvidenceLedger | null;
}

const formatPercent = (value: number | null | undefined): string => {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'N/A';
  const normalized = value > 1 ? value : value * 100;
  return `${Math.round(Math.max(0, Math.min(100, normalized)))}%`;
};

const sourceConfidence = (source: SourceRef): number | null => {
  if (typeof source.reliability === 'number') return source.reliability;
  if (typeof source.confidence === 'number') return source.confidence;
  return null;
};

const sourceDomain = (source: SourceRef): string => {
  if (source.url) {
    try {
      return new URL(source.url).hostname.replace(/^www\./, '');
    } catch {
      // fall through to source label
    }
  }
  return source.source || 'unknown';
};

const isExternalUrl = (url?: string | null): url is string => Boolean(url && /^https?:\/\//i.test(url));

const stanceTone = (stance?: string): string => {
  if (stance === 'bull') return 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-900/20 dark:text-emerald-200';
  if (stance === 'bear' || stance === 'risk') return 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900/60 dark:bg-rose-900/20 dark:text-rose-200';
  if (stance === 'neutral') return 'border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-900/60 dark:bg-blue-900/20 dark:text-blue-200';
  return 'border-fin-border bg-fin-bg-secondary text-fin-muted';
};

const linkedSources = (claim: ResearchClaim, sourcesById: Map<string, SourceRef>): SourceRef[] =>
  (claim.evidence_ids || [])
    .map((sourceId) => sourcesById.get(sourceId))
    .filter((source): source is SourceRef => Boolean(source));

export const EvidenceLedgerPanel: React.FC<EvidenceLedgerPanelProps> = ({ ledger }) => {
  const claims = ledger?.claims || [];
  const sources = ledger?.sources || [];
  const sourcesById = new Map(sources.map((source) => [source.source_id, source]));

  return (
    <details className="group rounded-xl border border-fin-border bg-fin-card overflow-hidden" open>
      <summary className="px-4 py-3 cursor-pointer hover:bg-fin-hover transition-colors flex items-center gap-2">
        <ChevronDown size={16} className="text-fin-muted group-open:rotate-180 transition-transform" />
        <FileSearch size={15} className="text-fin-primary" />
        <span className="text-sm font-semibold text-fin-text">证据账本</span>
        <span className="ml-auto text-2xs text-fin-muted">
          {ledger ? `${claims.length} claims · ${sources.length} sources` : 'missing'}
        </span>
      </summary>

      {!ledger ? (
        <div className="px-4 pb-4">
          <div className="rounded-lg border border-dashed border-fin-border bg-fin-bg-secondary/60 px-3 py-3 text-xs text-fin-muted">
            暂无证据账本
          </div>
        </div>
      ) : (
        <div className="px-4 pb-4 space-y-3">
          {sources.length > 0 && (
            <div className="overflow-hidden rounded-lg border border-fin-border bg-fin-bg">
              <div className="grid grid-cols-[minmax(0,1fr)_96px_96px_64px] gap-2 border-b border-fin-border bg-fin-bg-secondary px-3 py-2 text-2xs font-medium uppercase tracking-wide text-fin-muted">
                <span>Source</span>
                <span>As of</span>
                <span>Confidence</span>
                <span>Layer</span>
              </div>
              <div className="divide-y divide-fin-border/70">
                {sources.slice(0, 8).map((source) => {
                  const externalUrl = isExternalUrl(source.url) ? source.url : null;
                  return (
                    <div
                      key={source.source_id}
                      className="grid grid-cols-[minmax(0,1fr)_96px_96px_64px] gap-2 px-3 py-2 text-xs text-fin-text"
                    >
                      <div className="min-w-0">
                        <div className="flex min-w-0 items-center gap-1.5">
                          {externalUrl ? (
                            <a
                              href={externalUrl}
                              target="_blank"
                              rel="noreferrer"
                              className="truncate font-medium text-fin-primary hover:underline"
                            >
                              {source.title || source.source_id}
                            </a>
                          ) : (
                            <span className="truncate font-medium">{source.title || source.source_id}</span>
                          )}
                          {externalUrl && <ExternalLink size={11} className="shrink-0 text-fin-muted" />}
                          <SourceTrustBadge
                            sourceId={source.source_id}
                            sourceType={typeof source.source_type === 'string' ? source.source_type : undefined}
                            fallbackUsed={Boolean(source.fallback_used)}
                            degraded={Boolean(source.degraded_mode)}
                            status={typeof source.status === 'string' ? source.status : undefined}
                            className="shrink-0"
                          />
                        </div>
                        <div className="mt-0.5 truncate text-2xs text-fin-muted">{sourceDomain(source)}</div>
                      </div>
                      <span className="truncate text-2xs text-fin-text-secondary" title={source.as_of || undefined}>
                        {source.as_of || source.published_date || 'N/A'}
                      </span>
                      <span className="tabular-nums text-2xs text-fin-text-secondary">
                        {formatPercent(sourceConfidence(source))}
                      </span>
                      <span className="h-fit w-fit rounded border border-fin-border bg-fin-card px-1.5 py-0.5 text-2xs font-medium text-fin-text-secondary">
                        {source.layer || 'n/a'}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          <div className="space-y-2">
            {claims.slice(0, 5).map((claim) => {
              const claimSources = linkedSources(claim, sourcesById);
              return (
                <div key={claim.claim_id} className="rounded-lg border border-fin-border bg-fin-bg px-3 py-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={`rounded border px-1.5 py-0.5 text-2xs font-medium ${stanceTone(claim.stance)}`}>
                      {claim.stance || 'unknown'}
                    </span>
                    <span className="text-2xs tabular-nums text-fin-muted">
                      confidence {formatPercent(claim.confidence)}
                    </span>
                    {claim.agent_name && (
                      <span className="text-2xs text-fin-muted">{claim.agent_name}</span>
                    )}
                  </div>
                  <div className="mt-1 text-xs leading-relaxed text-fin-text">{claim.claim}</div>
                  {claimSources.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {claimSources.map((source) => (
                        <span
                          key={`${claim.claim_id}-${source.source_id}`}
                          className="rounded bg-fin-bg-secondary px-1.5 py-0.5 text-2xs text-fin-text-secondary"
                        >
                          {source.title || source.source_id}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}

            {claims.length === 0 && (
              <div className="rounded-lg border border-dashed border-fin-border bg-fin-bg-secondary/50 px-3 py-2 text-xs text-fin-muted">
                暂无结构化 claim
              </div>
            )}
          </div>
        </div>
      )}
    </details>
  );
};
