import { Activity, Bell, RefreshCw, Sparkles, TrendingUp, X } from 'lucide-react';
import type { FC, ReactNode } from 'react';
import type { RightPanelTab } from './types';

const TabButton: FC<{
  active: boolean;
  onClick: () => void;
  title: string;
  icon: ReactNode;
  badge?: number;
  testId?: string;
}> = ({ active, onClick, title, icon, badge, testId }) => (
  <button
    type="button"
    title={title}
    onClick={onClick}
    data-testid={testId}
    className={`relative p-2 rounded-lg transition-colors ${
      active ? 'bg-fin-primary/10 text-fin-primary' : 'text-fin-muted hover:text-fin-text hover:bg-fin-hover'
    }`}
  >
    {icon}
    {badge !== undefined && badge > 0 && (
      <span className="absolute -top-0.5 -right-0.5 w-4 h-4 bg-fin-danger text-white text-[9px] font-bold rounded-full flex items-center justify-center">
        {badge > 9 ? '9+' : badge}
      </span>
    )}
  </button>
);

type RightPanelHeaderProps = {
  activeTab: RightPanelTab;
  alertsCount: number;
  executionCount: number;
  loading: boolean;
  onTabChange: (tab: RightPanelTab) => void;
  onRefresh: () => void;
  onCollapse: () => void;
};

export function RightPanelHeader({
  activeTab,
  alertsCount,
  executionCount,
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
          testId="context-tab-execution"
        />
      </div>
      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={onRefresh}
          className="p-1.5 hover:bg-fin-hover rounded text-fin-muted hover:text-fin-text transition-colors"
          title="Refresh"
        >
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
        </button>
        <button
          type="button"
          onClick={onCollapse}
          className="p-1.5 hover:bg-fin-hover rounded text-fin-muted hover:text-fin-text transition-colors"
          title="Collapse"
        >
          <X size={12} />
        </button>
      </div>
    </div>
  );
}
