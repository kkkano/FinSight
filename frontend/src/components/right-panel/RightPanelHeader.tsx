import { Sparkles, TrendingUp, X } from 'lucide-react';
import type { FC, ReactNode } from 'react';

import { Tooltip } from '../ui/Tooltip';
import type { RightPanelTab } from './types';

const TabButton: FC<{
  active: boolean;
  onClick: () => void;
  title: string;
  icon: ReactNode;
  badge?: number;
  pulse?: boolean;
  testId: string;
}> = ({ active, onClick, title, icon, badge, pulse = false, testId }) => (
  <Tooltip content={title}>
    <button
      type="button"
      aria-label={title}
      onClick={onClick}
      data-testid={testId}
      className={`relative p-2 rounded-lg transition-colors ${
        active
          ? 'bg-fin-primary/10 text-fin-primary'
          : `text-fin-muted hover:text-fin-text hover:bg-fin-hover ${pulse ? 'ring-1 ring-fin-primary/50' : ''}`
      }`}
    >
      {icon}
      {pulse && <span className="absolute -right-1 -top-1 h-2.5 w-2.5 rounded-full bg-fin-primary" />}
      {badge !== undefined && badge > 0 && (
        <span className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-fin-danger px-1 text-[9px] font-bold text-white">
          {badge > 9 ? '9+' : badge}
        </span>
      )}
    </button>
  </Tooltip>
);

type RightPanelHeaderProps = {
  activeTab: RightPanelTab;
  executionCount: number;
  hasUnseenExecution: boolean;
  onTabChange: (tab: RightPanelTab) => void;
  onCollapse: () => void;
};

export function RightPanelHeader({
  activeTab,
  executionCount,
  hasUnseenExecution,
  onTabChange,
  onCollapse,
}: RightPanelHeaderProps) {
  return (
    <div className="flex items-center justify-between border-b border-fin-border bg-fin-bg/50 px-2 py-1.5">
      <div className="flex items-center gap-1">
        <TabButton
          active={activeTab === 'chart'}
          onClick={() => onTabChange('chart')}
          title="市场图表"
          icon={<TrendingUp size={14} />}
          testId="context-tab-chart"
        />
        <TabButton
          active={activeTab === 'execution'}
          onClick={() => onTabChange('execution')}
          title="执行状态"
          icon={<Sparkles size={14} />}
          badge={executionCount}
          pulse={hasUnseenExecution && activeTab !== 'execution'}
          testId="context-tab-execution"
        />
      </div>
      <Tooltip content="收起">
        <button
          type="button"
          onClick={onCollapse}
          className="p-1.5 text-fin-muted transition-colors hover:bg-fin-hover hover:text-fin-text"
          aria-label="收起"
        >
          <X size={12} />
        </button>
      </Tooltip>
    </div>
  );
}
