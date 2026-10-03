import { AgentLogPanel } from '../agent-log';
import { Dashboard } from '../../pages/Dashboard';
import { useDeveloperMode } from '../../hooks/useDeveloperMode';

type DashboardWorkspaceProps = {
  symbol: string | null;
  onBackToChat: () => void;
  onSymbolChange: (symbol: string) => void;
};

export function DashboardWorkspace({
  symbol,
  onBackToChat,
  onSymbolChange,
}: DashboardWorkspaceProps) {
  const [developerMode] = useDeveloperMode();

  return (
    <div className="h-full flex-1 min-w-0 flex min-h-0 overflow-hidden relative max-lg:flex-col">
      <div className="h-full flex-1 min-w-0 min-h-0 flex flex-col overflow-hidden">
        <Dashboard
          initialSymbol={symbol ?? undefined}
          onBackToChat={onBackToChat}
          onSymbolChange={onSymbolChange}
        />
        {developerMode && (
          <div className="shrink-0 px-4 pb-4 max-lg:px-3 max-lg:pb-3">
            <AgentLogPanel />
          </div>
        )}
      </div>

    </div>
  );
}
