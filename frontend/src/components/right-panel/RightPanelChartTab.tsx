import { useEffect, useMemo, useRef, useState } from 'react';
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
  const [isChartMaximized, setIsChartMaximized] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const activeSymbol = useDashboardStore((state) => state.activeAsset?.symbol);
  const currentTicker = useStore((state) => state.currentTicker);
  const symbol = (activeSymbol || currentTicker || '').trim().toUpperCase();
  const [marketSeries, setMarketSeries] = useState<SmartChartData | null>(null);
  const [source, setSource] = useState<string>('market_chart');
  const [asOf, setAsOf] = useState<string | undefined>();
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!isChartMaximized) return;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    closeButtonRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        setIsChartMaximized(false);
      }
      if (event.key !== 'Tab') return;
      const controls = dialogRef.current?.querySelectorAll<HTMLElement>(
        'button, a[href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
      );
      if (!controls?.length) return;
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener('keydown', handleKeyDown);
      previousFocus?.focus();
    };
  }, [isChartMaximized]);

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
    title: symbol ? `${symbol} 日线行情` : '日线行情',
    symbol,
    source,
    fields: 'open,close,low,high,volume',
    asOf,
  }), [asOf, source, symbol]);

  const lastClose = marketSeries?.values.at(-1);
  const previousClose = marketSeries?.values.at(-2);
  const dailyChange = lastClose !== undefined && previousClose
    ? ((lastClose - previousClose) / previousClose) * 100
    : undefined;
  const formatPrice = (value: number) => value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  const renderChart = (expanded = false) => loading ? (
    <div className="flex h-full items-center justify-center text-sm text-t-text2" role="status">
      <Loader2 className="mr-2 animate-spin" size={16} /> 正在加载真实行情…
    </div>
  ) : marketSeries ? (
    <SmartChartRenderer
      block={expanded && marketSeries.volume?.some((value) => value > 0) ? { ...block, type: 'price_volume' } : block}
      marketSeries={marketSeries}
      fillContainer
      showTitle={false}
    />
  ) : (
    <div className="flex h-full items-center justify-center">
      <EmptyState icon={ChartNoAxesCombined} message={symbol ? '真实行情暂不可用' : '选择标的后查看真实行情'} />
    </div>
  );

  return (
    <>
      <div className="flex h-full min-h-0 flex-col overflow-hidden p-3">
        <div className="mb-3 flex shrink-0 items-center justify-between gap-2">
          <div className="min-w-0">
            <span className="text-sm font-semibold text-t-text">{symbol || '市场'} 行情</span>
            <span className="ml-2 text-xs text-t-text2">日线</span>
          </div>
          <button
            type="button"
            onClick={() => setIsChartMaximized(true)}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-t-text2 transition-colors hover:bg-t-hover hover:text-t-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-t-accent"
            title="放大行情图"
            aria-label="放大行情图"
          >
            <Maximize2 size={16} />
          </button>
        </div>
        <div className="min-h-0 flex-1">
          {renderChart()}
        </div>
      </div>

      <Dialog
        open={isChartMaximized}
        onClose={() => setIsChartMaximized(false)}
        labelledBy="right-panel-chart-title"
        overlayClassName="!p-2 sm:!p-6"
        panelClassName="h-[90dvh] max-h-[900px] w-full max-w-7xl overflow-hidden rounded-lg border border-t-border bg-t-surface shadow-2xl"
      >
        <div ref={dialogRef} className="flex h-full min-h-0 flex-col">
          <div className="flex shrink-0 flex-wrap items-center justify-between gap-x-6 gap-y-3 border-b border-t-divider px-4 py-4 sm:px-6">
            <div className="flex min-w-0 items-center gap-3">
              <TrendingUp className="shrink-0 text-t-accent" size={20} />
              <div>
                <h2 id="right-panel-chart-title" className="text-lg font-semibold text-t-text">
                  {symbol || '市场'} 行情
                </h2>
                <p className="mt-1 text-xs text-t-text2">日线 · 近一年</p>
              </div>
            </div>
            <button
              ref={closeButtonRef}
              type="button"
              onClick={() => setIsChartMaximized(false)}
              className="flex h-9 w-9 items-center justify-center rounded-md text-t-text2 transition-colors hover:bg-t-hover hover:text-t-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-t-accent sm:order-last"
              title="关闭行情图"
              aria-label="关闭行情图"
            >
              <X size={20} />
            </button>
            {!loading && lastClose !== undefined && (
              <dl className="flex w-full items-baseline gap-5 sm:ml-auto sm:w-auto">
                <div className="flex items-baseline gap-2">
                  <dt className="text-xs text-t-text2">收盘</dt>
                  <dd className="num text-xl font-semibold text-t-text">{formatPrice(lastClose)}</dd>
                </div>
                {dailyChange !== undefined && (
                  <div className="flex items-baseline gap-2">
                    <dt className="text-xs text-t-text2">当日</dt>
                    <dd className={`num text-sm ${dailyChange > 0 ? 'text-t-up' : dailyChange < 0 ? 'text-t-down' : 'text-t-text2'}`}>
                      {dailyChange > 0 ? '+' : ''}{dailyChange.toFixed(2)}%
                    </dd>
                  </div>
                )}
              </dl>
            )}
          </div>
          <div className="min-h-0 flex-1 overflow-hidden px-2 py-3 sm:px-5 sm:py-4">
            {renderChart(true)}
          </div>
        </div>
      </Dialog>
    </>
  );
}
