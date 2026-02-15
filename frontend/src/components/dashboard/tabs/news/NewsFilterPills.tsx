/**
 * NewsFilterPills - Filter pills for news sentiment filtering.
 *
 * Controlled component: activeFilter + onFilterChange props.
 */

export type NewsFilterType = 'all' | 'bullish' | 'neutral' | 'bearish';

interface NewsFilterPillsProps {
  activeFilter: NewsFilterType;
  onFilterChange: (filter: NewsFilterType) => void;
}

const PILLS: { key: NewsFilterType; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'bullish', label: '看多' },
  { key: 'neutral', label: '中性' },
  { key: 'bearish', label: '看空' },
];

export function NewsFilterPills({ activeFilter, onFilterChange }: NewsFilterPillsProps) {
  return (
    <div className="flex items-center gap-2">
      {PILLS.map((pill) => {
        const isActive = pill.key === activeFilter;
        return (
          <button
            key={pill.key}
            type="button"
            onClick={() => onFilterChange(pill.key)}
            className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
              isActive
                ? 'bg-fin-primary text-white'
                : 'bg-fin-bg-secondary text-fin-muted hover:text-fin-text'
            }`}
          >
            {pill.label}
          </button>
        );
      })}
    </div>
  );
}

export default NewsFilterPills;
