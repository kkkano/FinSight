import { useEffect, useMemo, useState } from 'react';
import { ChartNoAxesCombined, Loader2, Maximize2, TrendingUp, X } from 'lucide-react';

import { apiClient } from '../../api/client';
import { useDashboardStore } from '../../store/dashboardStore';
import { useStore } from '../../store/useStore';
import type { KlineData } from '../../types';
import {
  buildKlineSmartChartData,
  SmartChartRenderer,
  type SmartChartBlock,
  type SmartChartData,
} from '../SmartChart';
import { Dialog } from '../ui/Dialog';
import { EmptyState } from '../ui/EmptyState';

export function RightPanelChartTab() {
  const [chartHeight, setChartHeight] = useState(250);
  const [isChartMaximized, setIsChartMaximized] = useState(false);
  const activeSymbol = useDashboardStore((state) => state.activeAsset?.symbol);
  const currentTicker = useStore((state) => state.currentTicker);
  const symbol = (activeSymbol || currentTicker || '').trim().toUpperCase();
  const [marketSeries, setMarketSeries] = useState<SmartChartData | null>(null);
  const [source, setSource] = useState<string>('market_chart');
  const [asOf, setAsOf] = useState<string | undefined>();
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!symbol) {
      setMarketSeries(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    apiClient.fetchKline(symbol, '1y', '1d')
      .then((response) => {
        if (cancelled) return;
        const payload = response?.data;
        const rows = Array.isArray(payload?.kline_data) ? payload.kline_data as KlineData[] : [];
        setMarketSeries(rows.length > 0 ? buildKlineSmartChartData(rows) : null);
        setSource(typeof payload?.source === 'string' ? payload.source : 'market_chart');
        setAsOf(typeof payload?.as_of === 'string' ? payload.as_of : undefined);
      })
      .catch(() => {
        if (!cancelled) setMarketSeries(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [symbol]);

  const block = useMemo<SmartChartBlock>(() => ({
    mode: 'ref',
    type: 'candlestick',
    title: symbol ? `${symbol} 真实行情` : '真实行情',
    symbol,
    source,
    fields: 'open,close,low,high,volume',
    asOf,
  }), [asOf, source, symbol]);

  const chart = loading ? (
    <div className="flex h-full items-center justify-center text-xs text-fin-muted">
      <Loader2 className="mr-2 animate-spin" size={16} /> 正在加载真实行情…
    </div>
  ) : marketSeries ? (
    <SmartChartRenderer block={block} marketSeries={marketSeries} />
  ) : (
    <EmptyState icon={ChartNoAxesCombined} message={symbol ? '真实行情暂不可用' : '选择标的后查看真实行情'} />
  );

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
            {chart}
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

      <Dialog
        open={isChartMaximized}
        onClose={() => setIsChartMaximized(false)}
        labelledBy="right-panel-chart-title"
        overlayClassName="p-6"
        panelClassName="bg-fin-panel border border-fin-border rounded-xl w-full max-w-5xl h-[80vh] flex flex-col shadow-2xl"
      >
        <div className="flex items-center justify-between p-4 border-b border-fin-border/50">
          <div className="flex items-center gap-2">
            <TrendingUp className="text-fin-primary" size={20} />
            <h2 id="right-panel-chart-title" className="font-bold text-lg text-fin-text">
              Market Chart (Full View)
            </h2>
          </div>
          <button
            type="button"
            onClick={() => setIsChartMaximized(false)}
            className="p-2 hover:bg-fin-hover rounded-full text-fin-muted hover:text-fin-text transition-colors"
            aria-label="Close full chart"
          >
            <X size={20} />
          </button>
        </div>
        <div className="flex-1 p-4 overflow-hidden bg-fin-bg-secondary/30">
          {chart}
        </div>
      </Dialog>
    </>
  );
}
