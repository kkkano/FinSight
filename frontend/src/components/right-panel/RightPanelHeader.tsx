import { Maximize2, Minimize2, Sparkles, Target, TrendingUp, X } from 'lucide-react';
import type { FC, ReactNode } from 'react';

import { Tooltip } from '../ui/Tooltip';
import type { RightPanelTab } from './types';

const TabButton: FC<{
  active: boolean;
  onClick: () => void;
  title: string;
  label: string;
  icon: ReactNode;
  badge?: number;
  pulse?: boolean;
  testId: string;
}> = ({ active, onClick, title, label, icon, badge, pulse = false, testId }) => (
    <button
      type="button"
      aria-label={title}
      title={title}
      aria-pressed={active}
      onClick={onClick}
      data-testid={testId}
      className={`relative flex h-9 items-center gap-1.5 rounded-md px-2 text-sm font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-t-accent ${
        active
          ? 'bg-t-accent/10 text-t-accent'
          : `text-t-text2 hover:text-t-text hover:bg-t-hover ${pulse ? 'ring-1 ring-t-accent/40' : ''}`
      }`}
    >
      {icon}
      <span>{label}</span>
      {pulse && <span className="absolute right-0 top-0 h-2 w-2 rounded-full bg-t-accent" />}
      {badge !== undefined && badge > 0 && (
        <span className="num flex h-5 min-w-5 items-center justify-center rounded bg-t-accent/10 px-1 text-xs font-semibold text-t-accent">
          {badge > 9 ? '9+' : badge}
        </span>
      )}
    </button>
);

type RightPanelHeaderProps = {
  activeTab: RightPanelTab;
  executionCount: number;
  hasUnseenExecution: boolean;
  onTabChange: (tab: RightPanelTab) => void;
  onCollapse: () => void;
  onToggleExpanded?: () => void;
  isExpanded?: boolean;
};

export function RightPanelHeader({
  activeTab,
  executionCount,
  hasUnseenExecution,
  onTabChange,
  onCollapse,
  onToggleExpanded,
  isExpanded = false,
}: RightPanelHeaderProps) {
  return (
    <div className="flex shrink-0 items-center justify-between gap-1 border-b border-t-divider bg-t-card px-2 py-2">
      <div className="flex min-w-0 items-center gap-0.5">
        <TabButton
          active={activeTab === 'chart'}
          onClick={() => onTabChange('chart')}
          title="市场图表"
          label="图表"
          icon={<TrendingUp size={16} />}
          testId="context-tab-chart"
        />
        <TabButton
          active={activeTab === 'execution'}
          onClick={() => onTabChange('execution')}
          title="执行状态"
          label="进度"
          icon={<Sparkles size={16} />}
          badge={executionCount}
          pulse={hasUnseenExecution && activeTab !== 'execution'}
          testId="context-tab-execution"
        />
        <TabButton
          active={activeTab === 'track-record'}
          onClick={() => onTabChange('track-record')}
          title="预测战绩"
          label="战绩"
          icon={<Target size={16} />}
          testId="context-tab-track-record"
        />
      </div>
      <div className="flex shrink-0 items-center gap-0.5">
        {onToggleExpanded && (
          <Tooltip content={isExpanded ? '收起详情' : '展开详情'}>
            <button
              type="button"
              onClick={onToggleExpanded}
              className="flex h-9 w-9 items-center justify-center rounded-md text-t-text2 transition-colors hover:bg-t-hover hover:text-t-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-t-accent"
              aria-label={isExpanded ? '收起详情' : '展开详情'}
              aria-expanded={isExpanded}
            >
              {isExpanded ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
            </button>
          </Tooltip>
        )}
        <Tooltip content="收起">
          <button
            type="button"
            onClick={onCollapse}
            className="flex h-9 w-9 items-center justify-center rounded-md text-t-text2 transition-colors hover:bg-t-hover hover:text-t-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-t-accent"
            aria-label="收起"
          >
            <X size={16} />
          </button>
        </Tooltip>
      </div>
    </div>
  );
}
