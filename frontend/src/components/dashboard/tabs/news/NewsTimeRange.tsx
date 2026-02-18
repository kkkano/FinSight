/**
 * NewsTimeRange — Compact time range selector (24h / 7d / 30d).
 *
 * Renders as a right-aligned button group.
 */
import type { NewsTimeRange as TimeRangeType } from '../../../../types/dashboard';

interface NewsTimeRangeProps {
  activeRange: TimeRangeType;
  onRangeChange: (range: TimeRangeType) => void;
}

const RANGES: { key: TimeRangeType; label: string }[] = [
  { key: '24h', label: '24h' },
  { key: '7d', label: '7d' },
  { key: '30d', label: '30d' },
];

export function NewsTimeRange({ activeRange, onRangeChange }: NewsTimeRangeProps) {
  return (
    <div className="flex items-center bg-fin-bg-secondary rounded-md p-0.5 shrink-0">
      {RANGES.map(({ key, label }) => {
        const isActive = key === activeRange;
        return (
          <button
            key={key}
            type="button"
            onClick={() => onRangeChange(key)}
            className={`px-2 py-0.5 rounded text-2xs font-medium transition-colors ${
              isActive
                ? 'bg-fin-card text-fin-text shadow-sm'
                : 'text-fin-muted hover:text-fin-text'
            }`}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}

export default NewsTimeRange;
