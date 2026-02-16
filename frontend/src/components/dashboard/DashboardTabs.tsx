/**
 * DashboardTabs - Tab navigation for the v2 dashboard.
 *
 * Provides 6 tabs synced with the URL query param `?tab=`:
 *   overview | financial | technical | news | research | peers
 *
 * Tabs 4-6 (news, research, peers) render real panel components;
 * Tabs 1-3 (overview, financial, technical) also render real panel components.
 */
import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';

import { OverviewTab } from './tabs/OverviewTab.tsx';
import { FinancialTab } from './tabs/FinancialTab.tsx';
import { TechnicalTab } from './tabs/TechnicalTab.tsx';
import { NewsTab } from './tabs/NewsTab.tsx';
import { ResearchTab } from './tabs/ResearchTab.tsx';
import { PeersTab } from './tabs/PeersTab.tsx';

// --- Tab Definition ---

export type DashboardTabKey =
  | 'overview'
  | 'financial'
  | 'technical'
  | 'news'
  | 'research'
  | 'peers';

interface TabDef {
  key: DashboardTabKey;
  label: string;
}

const TABS: readonly TabDef[] = [
  { key: 'overview', label: '综合分析' },
  { key: 'financial', label: '财务报表' },
  { key: 'technical', label: '技术面' },
  { key: 'news', label: '新闻动态' },
  { key: 'research', label: '深度研究' },
  { key: 'peers', label: '同行对比' },
] as const;

const VALID_KEYS = new Set<string>(TABS.map((t) => t.key));
const DEFAULT_TAB: DashboardTabKey = 'overview';

// --- Component ---

export function DashboardTabs() {
  const [searchParams, setSearchParams] = useSearchParams();

  const activeTab: DashboardTabKey = useMemo(() => {
    const raw = searchParams.get('tab');
    if (raw && VALID_KEYS.has(raw)) return raw as DashboardTabKey;
    return DEFAULT_TAB;
  }, [searchParams]);

  const handleTabChange = useCallback(
    (key: DashboardTabKey) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (key === DEFAULT_TAB) {
            next.delete('tab');
          } else {
            next.set('tab', key);
          }
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  return (
    <div className="flex flex-col flex-1 min-h-0 overflow-hidden">
      {/* Tab bar */}
      <div className="flex items-end gap-0 border-b border-fin-border bg-fin-card px-5 overflow-x-auto scrollbar-hide shrink-0 max-lg:px-3">
        {TABS.map((tab) => {
          const isActive = tab.key === activeTab;
          return (
            <button
              key={tab.key}
              type="button"
              onClick={() => handleTabChange(tab.key)}
              data-testid={`dashboard-tab-${tab.key}`}
              className={`relative px-4 py-2.5 text-sm font-medium transition-colors whitespace-nowrap ${
                isActive
                  ? 'text-fin-primary'
                  : 'text-fin-muted hover:text-fin-text'
              }`}
            >
              {tab.label}
              {/* Active underline */}
              {isActive && (
                <span className="absolute bottom-0 left-2 right-2 h-0.5 bg-fin-primary rounded-full" />
              )}
            </button>
          );
        })}
      </div>

      {/* Tab panel */}
      <div className="flex-1 min-h-0 overflow-y-auto">
        <div className="p-5 max-lg:p-3">
          {activeTab === 'overview' && <OverviewTab />}
          {activeTab === 'financial' && <FinancialTab />}
          {activeTab === 'technical' && <TechnicalTab />}
          {activeTab === 'news' && <NewsTab />}
          {activeTab === 'research' && <ResearchTab />}
          {activeTab === 'peers' && <PeersTab />}
        </div>
      </div>
    </div>
  );
}

export default DashboardTabs;
