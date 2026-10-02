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
  autoSwitchExecution?: boolean;
};

export function ContextPanelShell({
  isMobile,
  panelWidth,
  isExpanded,
  onExpand,
  onCollapse,
  onResizeStart,
  autoSwitchExecution = true,
}: ContextPanelShellProps) {
  if (!isExpanded) {
    return (
      <button
        type="button"
        data-testid="context-panel-expand"
        onClick={onExpand}
        className="absolute right-3 bottom-3 z-20 min-h-11 min-w-11 p-2 rounded-md border border-t-border bg-t-card text-t-text2 hover:text-t-accent hover:border-t-accent transition-colors shadow-sm flex items-center justify-center"
        title="展开右侧面板"
        aria-label="展开右侧面板"
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
            ? 'h-[42dvh] min-h-[300px] max-h-[480px] w-full shrink-0 border-t border-t-divider bg-t-bg p-3'
            : 'h-full shrink-0 border-l border-fin-border bg-fin-bg p-4'
        }
        style={!isMobile ? { width: panelWidth } : undefined}
      >
        <RightPanel
          onCollapse={onCollapse}
          autoSwitchExecution={autoSwitchExecution}
          className="h-full"
        />
      </aside>
    </>
  );
}
