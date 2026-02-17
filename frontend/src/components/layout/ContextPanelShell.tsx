import { ChevronLeft } from 'lucide-react';
import type { MouseEvent } from 'react';
import { RightPanel } from '../RightPanel';

export type ContextPanelShellProps = {
  isMobile: boolean;
  panelWidth: number;
  isExpanded: boolean;
  onExpand: () => void;
  onCollapse: () => void;
  onResizeStart: (event: MouseEvent) => void;
  onSubscribeClick: () => void;
  showMiniChat: boolean;
  autoSwitchExecution?: boolean;
  /** Callback to navigate to chat view (for execution bridge "继续追问"). */
  onNavigateToChat?: () => void;
};

export function ContextPanelShell({
  isMobile,
  panelWidth,
  isExpanded,
  onExpand,
  onCollapse,
  onResizeStart,
  onSubscribeClick,
  showMiniChat,
  autoSwitchExecution = true,
  onNavigateToChat,
}: ContextPanelShellProps) {
  if (!isExpanded) {
    return (
      <button
        type="button"
        data-testid="context-panel-expand"
        onClick={onExpand}
        className="absolute right-2 top-1/2 -translate-y-1/2 z-20 p-2 rounded-full border border-fin-border bg-fin-card text-fin-text-secondary hover:text-fin-primary hover:border-fin-primary transition-colors shadow-sm"
        title="展开右侧面板"
      >
        <ChevronLeft size={16} />
      </button>
    );
  }

  return (
    <>
      {!isMobile && (
        <div
          className="w-1.5 shrink-0 cursor-col-resize group flex items-center justify-center hover:bg-fin-primary/10 transition-colors"
          onMouseDown={onResizeStart}
          title="拖拽调整宽度"
        >
          <div className="w-0.5 h-16 rounded-full bg-fin-border group-hover:bg-fin-primary/60 transition-colors" />
        </div>
      )}

      <aside
        data-testid="context-panel-shell"
        className={
          isMobile
            ? 'w-full shrink-0 border-t border-fin-border bg-fin-bg p-3 max-h-[48vh] min-h-[320px]'
            : 'h-full shrink-0 border-l border-fin-border bg-fin-bg p-4'
        }
        style={!isMobile ? { width: panelWidth } : undefined}
      >
        <RightPanel
          onCollapse={onCollapse}
          onSubscribeClick={onSubscribeClick}
          onNavigateToChat={onNavigateToChat}
          showMiniChat={showMiniChat}
          autoSwitchExecution={autoSwitchExecution}
          className="h-full"
        />
      </aside>
    </>
  );
}
