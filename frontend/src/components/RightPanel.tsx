import { useState } from 'react';
import type { FC } from 'react';
import { MiniChat } from './MiniChat';
import { RightPanelHeader } from './right-panel/RightPanelHeader';
import { RightPanelAlertsTab } from './right-panel/RightPanelAlertsTab';
import { RightPanelPortfolioTab } from './right-panel/RightPanelPortfolioTab';
import { RightPanelChartTab } from './right-panel/RightPanelChartTab';
import { useRightPanelData } from './right-panel/useRightPanelData';
import type { RightPanelTab } from './right-panel/types';

type RightPanelProps = {
  onCollapse: () => void;
  onSubscribeClick?: () => void;
  showMiniChat?: boolean;
  className?: string;
};

export const RightPanel: FC<RightPanelProps> = ({
  onCollapse,
  onSubscribeClick,
  showMiniChat = true,
  className,
}) => {
  const [activeTab, setActiveTab] = useState<RightPanelTab>('alerts');
  const {
    alerts,
    loading,
    lastUpdated,
    refreshAll,
    positionRows,
    portfolioSummary,
    isPortfolioEditing,
    positionDrafts,
    setPositionDrafts,
    startPortfolioEdit,
    cancelPortfolioEdit,
    savePortfolioEdit,
  } = useRightPanelData();

  return (
    <section
      data-testid="context-panel"
      className={`flex flex-col h-full bg-fin-card border border-fin-border rounded-xl shadow-sm overflow-hidden ${className || ''}`}
    >
      <RightPanelHeader
        activeTab={activeTab}
        alertsCount={alerts.length}
        loading={loading}
        onTabChange={setActiveTab}
        onRefresh={refreshAll}
        onCollapse={onCollapse}
      />

      <div className="flex-1 min-h-0 overflow-hidden">
        {activeTab === 'alerts' && <RightPanelAlertsTab alerts={alerts} onSubscribeClick={onSubscribeClick} />}
        {activeTab === 'portfolio' && (
          <RightPanelPortfolioTab
            positionRows={positionRows}
            portfolioSummary={portfolioSummary}
            isPortfolioEditing={isPortfolioEditing}
            positionDrafts={positionDrafts}
            setPositionDrafts={setPositionDrafts}
            onStartPortfolioEdit={startPortfolioEdit}
            onCancelPortfolioEdit={cancelPortfolioEdit}
            onSavePortfolioEdit={savePortfolioEdit}
          />
        )}
        {activeTab === 'chart' && <RightPanelChartTab />}
      </div>

      {showMiniChat && (
        <div className="h-[45%] min-h-[180px] border-t border-fin-border flex flex-col">
          <MiniChat />
        </div>
      )}

      {lastUpdated && (
        <div className="text-[10px] text-fin-muted text-center py-1 border-t border-fin-border/50 shrink-0">
          Last updated: {lastUpdated.toLocaleTimeString()}
        </div>
      )}
    </section>
  );
};
