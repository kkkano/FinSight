import type { ReportIR } from '../../../../types';
import { ConflictMatrix } from './ConflictMatrix';
import {
  extractConflictDisclosure,
  extractConflictMatrixRows,
  hasStructuredConflict,
} from './conflictUtils';

interface ConflictItem {
  bullish?: string;
  bearish?: string;
  topic?: string;
  description?: string;
}

interface ConflictPanelProps {
  report: ReportIR | Record<string, unknown> | null;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : null;
}

function extractLegacyConflicts(report: Record<string, unknown>): ConflictItem[] {
  const candidates: unknown[] = [
    report.conflicts,
    report.viewpoint_conflicts,
    asRecord(report.analysis)?.conflicts,
  ];

  for (const candidate of candidates) {
    if (!Array.isArray(candidate) || candidate.length === 0) continue;
    return candidate.map((item: unknown) => {
      const conflict = asRecord(item) ?? {};
      return {
        bullish: (conflict.bullish as string) ?? (conflict.positive as string) ?? undefined,
        bearish: (conflict.bearish as string) ?? (conflict.negative as string) ?? undefined,
        topic: (conflict.topic as string) ?? (conflict.title as string) ?? undefined,
        description: (conflict.description as string) ?? undefined,
      };
    });
  }

  return [];
}

export function ConflictPanel({ report }: ConflictPanelProps) {
  const root = asRecord(report);
  if (!root) return null;

  const matrixRows = extractConflictMatrixRows(root);
  const hasMatrix = hasStructuredConflict(matrixRows);
  const legacyConflicts = extractLegacyConflicts(root);
  const disclosure = extractConflictDisclosure(root);

  const hasAnyConflict = hasMatrix || legacyConflicts.length > 0 || Boolean(disclosure);

  return (
    <div className="space-y-3">
      <h4 className="text-sm font-semibold text-fin-text">
        观点冲突
        {hasAnyConflict && (
          <span className="ml-2 text-xs text-fin-warning font-normal">
            (已检测)
          </span>
        )}
      </h4>

      <ConflictMatrix rows={matrixRows} />

      {!hasAnyConflict && (
        <div className="text-xs text-fin-muted border border-fin-border rounded-lg p-3">
          近期无显著冲突
        </div>
      )}

      {legacyConflicts.map((conflict, idx) => (
        <div
          key={`conflict-${idx}`}
          className="bg-fin-card border border-fin-border rounded-lg p-4"
        >
          {conflict.topic ? (
            <div className="text-sm font-medium text-fin-text mb-2">{conflict.topic}</div>
          ) : null}
          {conflict.description ? (
            <p className="text-xs text-fin-muted mb-3">{conflict.description}</p>
          ) : null}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div className="rounded-lg bg-fin-success/5 border border-fin-success/20 p-3">
              <div className="text-xs font-semibold text-fin-success mb-1">看多观点</div>
              <p className="text-xs text-fin-text-secondary leading-relaxed">{conflict.bullish ?? '--'}</p>
            </div>
            <div className="rounded-lg bg-fin-danger/5 border border-fin-danger/20 p-3">
              <div className="text-xs font-semibold text-fin-danger mb-1">看空观点</div>
              <p className="text-xs text-fin-text-secondary leading-relaxed">{conflict.bearish ?? '--'}</p>
            </div>
          </div>
        </div>
      ))}

      {!hasMatrix && disclosure && (
        <div className="rounded-lg border border-fin-warning/30 bg-fin-warning/5 p-3">
          <div className="text-xs font-semibold text-fin-warning mb-1">冲突披露</div>
          <pre className="text-2xs text-fin-text/80 whitespace-pre-wrap leading-relaxed">
            {disclosure}
          </pre>
        </div>
      )}
    </div>
  );
}

export default ConflictPanel;
