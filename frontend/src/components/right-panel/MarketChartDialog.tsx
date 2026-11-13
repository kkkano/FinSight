import { useEffect, useRef } from 'react';
import type { EChartsOption } from 'echarts';
import { X } from 'lucide-react';
import EChart from '../charts/EChart';
import { Dialog } from '../ui/Dialog';

export function MarketChartDialog({ open, onClose, symbol, period, option, closePrice, source }: {
  open: boolean; onClose: () => void; symbol: string; period: string;
  option: EChartsOption | null; closePrice?: number; source: string;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    closeButton.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); onClose(); }
      if (event.key === 'Tab') {
        const controls = panel.current?.querySelectorAll<HTMLElement>('button, [href], [tabindex]:not([tabindex="-1"])');
        if (!controls?.length) return;
        const first = controls[0]; const last = controls[controls.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener('keydown', handleKeyDown);
      previousFocus?.focus();
    };
  }, [open, onClose]);
  return <Dialog open={open} onClose={onClose} labelledBy="market-chart-title"
    overlayClassName="!z-[70] !p-2 sm:!p-6"
    panelClassName="h-[90dvh] max-h-[900px] w-full max-w-7xl overflow-hidden rounded-lg border border-t-border bg-t-surface shadow-2xl">
    <div ref={panel} className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-4 border-b border-t-divider px-4 py-4 sm:px-6">
        <div className="min-w-0"><h2 id="market-chart-title" className="text-lg font-semibold">{symbol} 行情</h2>
          <p className="text-xs text-t-text2">近 {period} · {source}</p></div>
        {closePrice !== undefined && <dl className="flex items-baseline gap-2"><dt className="text-xs text-t-text2">收盘</dt>
          <dd className="num text-xl">{closePrice.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</dd></dl>}
        <button ref={closeButton} type="button" onClick={onClose} aria-label="关闭行情图"
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-t-text2 hover:bg-t-hover"><X size={20} /></button>
      </div>
      <div className="min-h-0 flex-1 overflow-hidden px-2 py-3 sm:px-5 sm:py-4">
        {option && <EChart option={option} style={{ height: '100%' }} notMerge />}
      </div>
    </div>
  </Dialog>;
}
