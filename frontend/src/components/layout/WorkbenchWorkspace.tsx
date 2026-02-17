import type { MouseEvent } from 'react';

import Workbench from '../../pages/Workbench';
import { ContextPanelShell } from './ContextPanelShell';

type WorkbenchWorkspaceProps = {
  isMobile: boolean;
  symbol: string;
  fromDashboard: boolean;
  onNavigateToChat?: () => void;
  contextPanel: {
    panelWidth: number;
    isExpanded: boolean;
    onExpand: () => void;
    onCollapse: () => void;
    onResizeStart: (event: MouseEvent) => void;
    onSubscribeClick: () => void;
    autoSwitchExecution?: boolean;
    onNavigateToChat?: () => void;
  };
};

export function WorkbenchWorkspace({
  isMobile,
  symbol,
  fromDashboard,
  onNavigateToChat,
  contextPanel,
}: WorkbenchWorkspaceProps) {
  return (
    <div className="h-full flex-1 min-w-0 flex min-h-0 overflow-hidden relative max-lg:flex-col">
      <div className="h-full flex-1 min-w-0 min-h-0 overflow-y-auto p-5 max-lg:p-3">
        <Workbench
          symbol={symbol}
          fromDashboard={fromDashboard}
          onNavigateToChat={onNavigateToChat}
        />
      </div>

      <ContextPanelShell
        isMobile={isMobile}
        panelWidth={contextPanel.panelWidth}
        isExpanded={contextPanel.isExpanded}
        onExpand={contextPanel.onExpand}
        onCollapse={contextPanel.onCollapse}
        onResizeStart={contextPanel.onResizeStart}
        onSubscribeClick={contextPanel.onSubscribeClick}
        autoSwitchExecution={contextPanel.autoSwitchExecution}
        onNavigateToChat={contextPanel.onNavigateToChat}
        showMiniChat
      />
    </div>
  );
}
