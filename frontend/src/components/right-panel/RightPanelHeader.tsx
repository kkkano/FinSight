import { Activity, Bell, RefreshCw, Sparkles, TrendingUp, X } from 'lucide-react';
import type { FC, ReactNode } from 'react';
import type { RightPanelTab } from './types';
import { Tooltip } from '../ui/Tooltip';

const TabButton: FC<{
  active: boolean;
  onClick: () => void;
  title: string;
  icon: ReactNode;
  badge?: number;
  pulse?: boolean;
  testId?: string;
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
      {pulse && (
        <span className="absolute -top-1.5 -right-1.5 flex h-3 w-3">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-fin-primary/50 opacity-80" />
          <span className="relative inline-flex h-3 w-3 rounded-full bg-fin-primary" />
        </span>
      )}
      {badge !== undefined && badge > 0 && (
        <span className="absolute -top-0.5 -right-0.5 w-4 h-4 bg-fin-danger text-white text-[9px] font-bold rounded-full flex items-center justify-center">
          {badge > 9 ? '9+' : badge}
        </span>
      )}
    </button>
  </Tooltip>
);

type RightPanelHeaderProps = {
  activeTab: RightPanelTab;
  alertsCount: number;
  executionCount: number;
  hasUnseenExecution: boolean;
  loading: boolean;
  onTabChange: (tab: RightPanelTab) => void;
  onRefresh: () => void;
  onCollapse: () => void;
};

export function RightPanelHeader({
  activeTab,
  alertsCount,
  executionCount,
  hasUnseenExecution,
  loading,
  onTabChange,
  onRefresh,
  onCollapse,
}: RightPanelHeaderProps) {
  return (
    <div className="flex items-center justify-between px-2 py-1.5 border-b border-fin-border bg-fin-bg/50">
      <div className="flex items-center gap-1">
        <TabButton
          active={activeTab === 'alerts'}
          onClick={() => onTabChange('alerts')}
          title="消息中心"
          icon={<Bell size={14} />}
          badge={alertsCount}
          testId="context-tab-alerts"
        />
        <TabButton
          active={activeTab === 'portfolio'}
          onClick={() => onTabChange('portfolio')}
          title="资产组合"
          icon={<Activity size={14} />}
          testId="context-tab-portfolio"
        />
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
      <div className="flex items-center gap-1">
        <Tooltip content="Refresh">
          <button
            type="button"
            onClick={onRefresh}
            className="p-1.5 hover:bg-fin-hover rounded text-fin-muted hover:text-fin-text transition-colors"
            aria-label="Refresh"
          >
            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
          </button>
        </Tooltip>
        <Tooltip content="Collapse">
          <button
            type="button"
            onClick={onCollapse}
            className="p-1.5 hover:bg-fin-hover rounded text-fin-muted hover:text-fin-text transition-colors"
            aria-label="Collapse"
          >
            <X size={12} />
          </button>
        </Tooltip>
      </div>
    </div>
  );
}
