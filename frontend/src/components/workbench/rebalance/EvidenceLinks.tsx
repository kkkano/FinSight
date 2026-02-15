/**
 * EvidenceLinks — Display evidence snapshots from a rebalance action.
 *
 * Each evidence shows source name and a truncated quote excerpt.
 * Falls back to a "no evidence" message when list is empty.
 */
import { FileText } from 'lucide-react';

import type { EvidenceSnapshot } from '../../../types/dashboard.ts';

interface EvidenceLinksProps {
  snapshots: EvidenceSnapshot[];
}

const MAX_QUOTE_LENGTH = 120;

function truncateQuote(quote: string): string {
  if (quote.length <= MAX_QUOTE_LENGTH) return quote;
  return `${quote.slice(0, MAX_QUOTE_LENGTH)}...`;
}

export function EvidenceLinks({ snapshots }: EvidenceLinksProps) {
  if (snapshots.length === 0) {
    return (
      <p className="text-2xs text-fin-muted italic py-1">
        暂无引用来源
      </p>
    );
  }

  return (
    <ul className="space-y-1.5">
      {snapshots.map((snap) => (
        <li
          key={snap.evidence_id}
          className="flex items-start gap-2 text-2xs text-fin-text-secondary"
        >
          <FileText size={12} className="shrink-0 mt-0.5 text-fin-muted" />
          <div className="min-w-0">
            <span className="font-medium text-fin-text">{snap.source}</span>
            <span className="mx-1 text-fin-muted">--</span>
            <span className="text-fin-text-secondary">{truncateQuote(snap.quote)}</span>
          </div>
        </li>
      ))}
    </ul>
  );
}
