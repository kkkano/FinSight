/**
 * ConflictPanel - Display conflicting viewpoints from the report.
 *
 * Only renders when the report contains conflicts.
 * Shows bullish vs bearish viewpoints side by side.
 */

interface ConflictItem {
  bullish?: string;
  bearish?: string;
  topic?: string;
  description?: string;
}

interface ConflictPanelProps {
  report: Record<string, unknown> | null;
}

function extractConflicts(report: Record<string, unknown>): ConflictItem[] {
  const candidates: unknown[] = [
    report?.conflicts,
    report?.viewpoint_conflicts,
    (report?.analysis as Record<string, unknown>)?.conflicts,
  ];

  for (const candidate of candidates) {
    if (Array.isArray(candidate) && candidate.length > 0) {
      return candidate.map((item: unknown) => {
        const conflict = item as Record<string, unknown>;
        return {
          bullish: (conflict?.bullish as string) ?? (conflict?.positive as string) ?? undefined,
          bearish: (conflict?.bearish as string) ?? (conflict?.negative as string) ?? undefined,
          topic: (conflict?.topic as string) ?? (conflict?.title as string) ?? undefined,
          description: (conflict?.description as string) ?? undefined,
        };
      });
    }
  }

  return [];
}

export function ConflictPanel({ report }: ConflictPanelProps) {
  if (!report) return null;

  const conflicts = extractConflicts(report);
  if (conflicts.length === 0) return null;

  return (
    <div className="space-y-3">
      <h4 className="text-sm font-semibold text-fin-text">
        观点冲突
        <span className="ml-2 text-xs text-fin-warning font-normal">({conflicts.length})</span>
      </h4>
      {conflicts.map((conflict, idx) => (
        <div
          key={`conflict-${idx}`}
          className="bg-fin-card border border-fin-border rounded-lg p-4"
        >
          {conflict.topic ? (
            <div className="text-sm font-medium text-fin-text mb-3">{conflict.topic}</div>
          ) : null}
          {conflict.description ? (
            <p className="text-xs text-fin-muted mb-3">{conflict.description}</p>
          ) : null}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {/* Bullish side */}
            <div className="rounded-lg bg-fin-success/5 border border-fin-success/20 p-3">
              <div className="text-xs font-semibold text-fin-success mb-1">
                看多观点
              </div>
              <p className="text-xs text-fin-text-secondary leading-relaxed">
                {conflict.bullish ?? '--'}
              </p>
            </div>
            {/* Bearish side */}
            <div className="rounded-lg bg-fin-danger/5 border border-fin-danger/20 p-3">
              <div className="text-xs font-semibold text-fin-danger mb-1">
                看空观点
              </div>
              <p className="text-xs text-fin-text-secondary leading-relaxed">
                {conflict.bearish ?? '--'}
              </p>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

export default ConflictPanel;
