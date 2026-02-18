/**
 * NewsSubTabs — Primary tab selector for the news section.
 *
 * Three sub-tabs: stock-specific / market 7x24 / breaking events.
 * Renders as a pill-group with count badges.
 */
import { Flame, Globe, TrendingUp } from 'lucide-react';

import type { NewsSubTab } from '../../../../types/dashboard';

interface NewsSubTabsProps {
  activeTab: NewsSubTab;
  onTabChange: (tab: NewsSubTab) => void;
  ticker?: string;
  counts: { stock: number; market: number; breaking: number };
}

const TABS: { key: NewsSubTab; icon: typeof TrendingUp; getLabel: (ticker?: string) => string }[] = [
  { key: 'stock', icon: TrendingUp, getLabel: (t) => `${t ?? '个股'} 动态` },
  { key: 'market', icon: Globe, getLabel: () => '市场 7×24' },
  { key: 'breaking', icon: Flame, getLabel: () => '重大事件' },
];

export function NewsSubTabs({ activeTab, onTabChange, ticker, counts }: NewsSubTabsProps) {
  return (
    <div className="flex items-center gap-1.5 p-1 bg-fin-bg-secondary rounded-lg">
      {TABS.map(({ key, icon: Icon, getLabel }) => {
        const isActive = key === activeTab;
        const count = counts[key];

        return (
          <button
            key={key}
            type="button"
            onClick={() => onTabChange(key)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
              isActive
                ? 'bg-fin-card text-fin-text shadow-sm'
                : 'text-fin-muted hover:text-fin-text'
            }`}
          >
            <Icon size={13} className={isActive ? 'text-fin-primary' : ''} />
            <span>{getLabel(ticker)}</span>
            {count > 0 && (
              <span className={`ml-0.5 px-1.5 py-0.5 rounded-full text-2xs ${
                isActive
                  ? 'bg-fin-primary/15 text-fin-primary'
                  : 'bg-fin-border/50 text-fin-muted'
              }`}>
                {count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

export default NewsSubTabs;
