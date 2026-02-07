import { useEffect, useState } from 'react';
import { Maximize2, TrendingUp, X } from 'lucide-react';
import { StockChart } from '../StockChart';

export function RightPanelChartTab() {
  const [chartHeight, setChartHeight] = useState(250);
  const [isChartMaximized, setIsChartMaximized] = useState(false);

  useEffect(() => {
    const onEsc = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setIsChartMaximized(false);
    };
    window.addEventListener('keydown', onEsc);
    return () => window.removeEventListener('keydown', onEsc);
  }, []);

  return (
    <>
      <div className="flex-1 overflow-hidden p-3 flex flex-col">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-semibold text-fin-text-secondary">Market Chart</span>
          <button
            type="button"
            onClick={() => setIsChartMaximized(true)}
            className="p-1 hover:bg-fin-hover rounded text-fin-muted hover:text-fin-primary transition-colors"
            title="Maximize"
          >
            <Maximize2 size={12} />
          </button>
        </div>
        <div className="flex-1 relative min-h-0">
          <div style={{ height: chartHeight }} className="w-full bg-fin-bg-secondary/50 rounded-lg overflow-hidden">
            <StockChart />
          </div>
          <div
            className="absolute bottom-0 left-0 right-0 h-3 cursor-ns-resize bg-gradient-to-t from-fin-border/30 to-transparent flex items-center justify-center"
            onMouseDown={(event) => {
              const startY = event.clientY;
              const startHeight = chartHeight;
              const onMouseMove = (moveEvent: MouseEvent) => {
                const diff = moveEvent.clientY - startY;
                setChartHeight(Math.max(150, Math.min(500, startHeight + diff)));
              };
              const onMouseUp = () => {
                document.removeEventListener('mousemove', onMouseMove);
                document.removeEventListener('mouseup', onMouseUp);
              };
              document.addEventListener('mousemove', onMouseMove);
              document.addEventListener('mouseup', onMouseUp);
            }}
          >
            <div className="w-8 h-1 bg-fin-border rounded-full" />
          </div>
        </div>
      </div>

      {isChartMaximized && (
        <div className="fixed inset-0 z-[100] bg-black/80 backdrop-blur-sm flex items-center justify-center p-6">
          <div className="bg-fin-panel border border-fin-border rounded-xl w-full max-w-5xl h-[80vh] flex flex-col shadow-2xl">
            <div className="flex items-center justify-between p-4 border-b border-fin-border/50">
              <div className="flex items-center gap-2">
                <TrendingUp className="text-fin-primary" size={20} />
                <span className="font-bold text-lg text-fin-text">Market Chart (Full View)</span>
              </div>
              <button
                type="button"
                onClick={() => setIsChartMaximized(false)}
                className="p-2 hover:bg-fin-hover rounded-full text-fin-muted hover:text-fin-text transition-colors"
              >
                <X size={20} />
              </button>
            </div>
            <div className="flex-1 p-4 overflow-hidden bg-fin-bg-secondary/30">
              <StockChart />
            </div>
          </div>
        </div>
      )}
    </>
  );
}

