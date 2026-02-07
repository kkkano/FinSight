import { Moon, Sun } from 'lucide-react';
import type { MouseEvent } from 'react';
import { AgentLogPanel } from '../AgentLogPanel';
import { ChatInput } from '../ChatInput';
import { ChatList } from '../ChatList';
import { ContextPanelShell } from './ContextPanelShell';
import type { MarketQuote } from '../../hooks/useMarketQuotes';

type ChatWorkspaceProps = {
  isMobile: boolean;
  theme: 'dark' | 'light';
  onToggleTheme: () => void;
  onDashboardRequest: (symbol: string) => void;
  contextPanel: {
    panelWidth: number;
    isExpanded: boolean;
    onExpand: () => void;
    onCollapse: () => void;
    onResizeStart: (event: MouseEvent) => void;
    onSubscribeClick: () => void;
  };
  marketQuotes: MarketQuote[];
};

const formatChangePct = (value?: number) => {
  if (value === undefined || Number.isNaN(value)) return null;
  const sign = value >= 0 ? '+' : '';
  return `${sign}${value.toFixed(2)}%`;
};

export function ChatWorkspace({
  isMobile,
  theme,
  onToggleTheme,
  onDashboardRequest,
  contextPanel,
  marketQuotes,
}: ChatWorkspaceProps) {
  return (
    <div className="flex-1 min-w-0 flex flex-col h-full overflow-hidden relative">
      <header className="h-[60px] bg-fin-card border-b border-fin-border flex items-center justify-between px-6 shrink-0 max-lg:px-3">
        <div className="flex gap-4 text-xs text-fin-text font-medium overflow-x-auto scrollbar-none">
          {marketQuotes.map((quote) => (
            <span key={quote.label} className="flex items-center gap-1 whitespace-nowrap">
              {quote.flag} {quote.label}:{' '}
              {quote.loading ? (
                <span className="text-fin-muted">...</span>
              ) : quote.changePct !== undefined ? (
                <span className={quote.changePct >= 0 ? 'text-fin-success' : 'text-fin-danger'}>
                  {formatChangePct(quote.changePct)}
                </span>
              ) : quote.price !== undefined ? (
                <span className="text-fin-warning">${quote.price.toLocaleString()}</span>
              ) : (
                <span className="text-fin-muted">--</span>
              )}
            </span>
          ))}
        </div>

        <div className="flex items-center gap-3 shrink-0">
          <button
            type="button"
            onClick={onToggleTheme}
            className="p-2 rounded-lg border border-fin-border bg-fin-bg hover:bg-fin-hover transition-colors text-fin-text-secondary"
          >
            {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
          </button>
          <button
            type="button"
            className="px-3 py-1.5 rounded-lg border border-fin-border bg-fin-bg hover:bg-fin-hover transition-colors text-xs font-medium text-fin-text"
          >
            导出 PDF
          </button>
        </div>
      </header>

      <div className="flex-1 min-h-0 flex overflow-hidden p-5 gap-4 max-lg:flex-col max-lg:p-3">
        <div className="flex-1 min-w-0 min-h-0 flex flex-col gap-3 overflow-hidden">
          <div className="flex-1 bg-fin-card border border-fin-border rounded-2xl flex flex-col overflow-hidden shadow-sm min-h-0">
            <ChatList />
            <ChatInput onDashboardRequest={onDashboardRequest} />
          </div>
          <div className="shrink-0">
            <AgentLogPanel />
          </div>
        </div>

        <ContextPanelShell
          isMobile={isMobile}
          panelWidth={contextPanel.panelWidth}
          isExpanded={contextPanel.isExpanded}
          onExpand={contextPanel.onExpand}
          onCollapse={contextPanel.onCollapse}
          onResizeStart={contextPanel.onResizeStart}
          onSubscribeClick={contextPanel.onSubscribeClick}
          showMiniChat={false}
        />
      </div>
    </div>
  );
}
