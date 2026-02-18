import {
  CONFLICT_DIMENSIONS,
  type ConflictMatrixRow,
  dimensionLabel,
} from './conflictUtils';

interface ConflictMatrixProps {
  rows: ConflictMatrixRow[];
}

export function ConflictMatrix({ rows }: ConflictMatrixProps) {
  if (rows.length === 0) {
    return (
      <div className="text-xs text-fin-muted border border-fin-border rounded-lg p-3">
        近期无显著冲突
      </div>
    );
  }

  return (
    <div className="overflow-x-auto border border-fin-border rounded-lg">
      <table className="w-full text-2xs">
        <thead className="bg-fin-bg/60 text-fin-muted">
          <tr>
            <th className="text-left px-3 py-2 font-medium">Agent</th>
            {CONFLICT_DIMENSIONS.map((dimension) => (
              <th key={dimension} className="text-left px-2 py-2 font-medium">
                {dimensionLabel(dimension)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.agent} className="border-t border-fin-border/60">
              <td className="px-3 py-2 text-fin-text font-medium">{row.agent}</td>
              {CONFLICT_DIMENSIONS.map((dimension) => {
                const flags = row.cells[dimension];
                const hasConflict = flags.length > 0;
                return (
                  <td key={`${row.agent}-${dimension}`} className="px-2 py-2">
                    <span
                      className={`inline-flex items-center px-1.5 py-0.5 rounded ${
                        hasConflict
                          ? 'bg-fin-warning/15 text-fin-warning'
                          : 'bg-fin-bg text-fin-muted'
                      }`}
                      title={flags.join('\n')}
                    >
                      {hasConflict ? `冲突(${flags.length})` : '—'}
                    </span>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default ConflictMatrix;
