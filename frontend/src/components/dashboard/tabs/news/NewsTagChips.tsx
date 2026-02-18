/**
 * NewsTagChips — Secondary topic filter chips.
 *
 * Maps 18 backend tag rules into 7 user-friendly groups.
 * Only renders groups that have matching news in the current dataset.
 */
import type { NewsTagGroup } from '../../../../types/dashboard';

interface NewsTagChipsProps {
  activeTag: NewsTagGroup;
  onTagChange: (tag: NewsTagGroup) => void;
  availableGroups?: NewsTagGroup[];
}

const TAG_CONFIG: { key: NewsTagGroup; color: string }[] = [
  { key: '全部', color: '' },
  { key: '财报', color: 'bg-blue-500/15 text-blue-500 dark:text-blue-400' },
  { key: '科技', color: 'bg-purple-500/15 text-purple-500 dark:text-purple-400' },
  { key: '宏观', color: 'bg-orange-500/15 text-orange-500 dark:text-orange-400' },
  { key: '并购', color: 'bg-cyan-500/15 text-cyan-500 dark:text-cyan-400' },
  { key: '地缘', color: 'bg-red-500/15 text-red-500 dark:text-red-400' },
  { key: '行业', color: 'bg-emerald-500/15 text-emerald-500 dark:text-emerald-400' },
];

export function NewsTagChips({ activeTag, onTagChange, availableGroups }: NewsTagChipsProps) {
  const visibleTags = availableGroups
    ? TAG_CONFIG.filter((t) => t.key === '全部' || availableGroups.includes(t.key))
    : TAG_CONFIG;

  return (
    <div className="flex items-center gap-1.5 overflow-x-auto scrollbar-hide">
      {visibleTags.map(({ key, color }) => {
        const isActive = key === activeTag;
        return (
          <button
            key={key}
            type="button"
            onClick={() => onTagChange(key)}
            className={`shrink-0 px-2.5 py-1 rounded-full text-2xs font-medium transition-colors whitespace-nowrap ${
              isActive
                ? 'bg-fin-primary text-white'
                : color || 'bg-fin-bg-secondary text-fin-muted hover:text-fin-text'
            }`}
          >
            {key}
          </button>
        );
      })}
    </div>
  );
}

export default NewsTagChips;
