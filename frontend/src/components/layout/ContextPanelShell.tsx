import { ChevronLeft } from 'lucide-react';
import { useEffect, useRef, type MouseEvent } from 'react';
import { RightPanel } from '../RightPanel';
import { useIsMobileLayout } from '../../hooks/useIsMobileLayout';

export type ContextPanelShellProps = {
  isMobile: boolean;
  panelWidth: number;
  isExpanded: boolean;
  onExpand: () => void;
  onCollapse: () => void;
  onResizeStart: (event: MouseEvent) => void;
  autoSwitchExecution?: boolean;
  detailExpanded?: boolean;
  onToggleExpanded?: () => void;
  symbol?: string;
};

export function ContextPanelShell({
  isMobile,
  panelWidth,
  isExpanded,
  onExpand,
  onCollapse,
  onResizeStart,
  autoSwitchExecution = true,
  detailExpanded = false,
  onToggleExpanded,
  symbol,
}: ContextPanelShellProps) {
  const isNarrow = useIsMobileLayout('xl');
  const floating = isMobile || isNarrow || detailExpanded;
  const dialogRef = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!isExpanded || !floating) return;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const dialog = dialogRef.current;
    dialog?.querySelector<HTMLElement>('button')?.focus();
    const handleKeys = (event: KeyboardEvent) => {
      const modals = document.querySelectorAll('[role="dialog"][aria-modal="true"]');
      if (modals[modals.length - 1] !== dialog) return;
      if (event.key === 'Escape') { event.preventDefault(); onCollapse(); }
      if (event.key !== 'Tab' || !dialog) return;
      const controls = [...dialog.querySelectorAll<HTMLElement>('button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), summary, [tabindex="0"]')].filter((item) => item.getClientRects().length > 0);
      const first = controls[0];
      const last = controls.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    document.addEventListener('keydown', handleKeys);
    return () => { document.removeEventListener('keydown', handleKeys); previousFocus?.focus(); };
  }, [floating, isExpanded, onCollapse]);

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
      {floating && <div className="fixed inset-0 z-40 bg-black/35" onMouseDown={onCollapse} aria-hidden="true" />}
      {!floating && (
        <div
          className="w-1.5 shrink-0 cursor-col-resize group flex items-center justify-center hover:bg-fin-primary/10 transition-colors"
          onMouseDown={onResizeStart}
          title="拖拽调整宽度"
        >
          <div className="w-0.5 h-16 rounded-full bg-fin-border group-hover:bg-fin-primary/60 transition-colors" />
        </div>
      )}

      <aside
        ref={dialogRef}
        data-testid="context-panel-shell"
        role={floating ? 'dialog' : undefined}
        aria-modal={floating ? true : undefined}
        aria-label={floating ? '研究侧栏' : '研究摘要'}
        className={
          floating
            ? `fixed bottom-0 right-0 top-0 z-50 min-h-0 border-l border-t-border bg-t-surface shadow-xl ${isMobile ? 'w-full' : 'w-[640px] max-w-[calc(100vw-32px)]'}`
            : 'h-full min-h-0 shrink-0 border-l border-t-divider bg-t-surface'
        }
        style={!floating ? { width: panelWidth } : undefined}
      >
        <RightPanel
          onCollapse={onCollapse}
          autoSwitchExecution={autoSwitchExecution}
          className="h-full"
          detailExpanded={floating}
          onToggleExpanded={!isMobile && !isNarrow ? onToggleExpanded : undefined}
          symbol={symbol}
        />
      </aside>
    </>
  );
}
