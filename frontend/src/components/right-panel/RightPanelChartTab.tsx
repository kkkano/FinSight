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
import { CHART_RANGES, selectChartRange, type ChartRange } from './chartRange';

export function RightPanelChartTab({ symbol: selectedSymbol }: { symbol?: string } = {}) {
  const [isChartMaximized, setIsChartMaximized] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const activeSymbol = useDashboardStore((state) => state.activeAsset?.symbol);
  const currentTicker = useStore((state) => state.currentTicker);
  const symbol = (selectedSymbol || currentTicker || activeSymbol || '').trim().toUpperCase();
  const [marketSeries, setMarketSeries] = useState<SmartChartData | null>(null);
  const [source, setSource] = useState<string>('market_chart');
  const [asOf, setAsOf] = useState<string | undefined>();
  const [loading, setLoading] = useState(false);
  const [range, setRange] = useState<ChartRange>('3m');

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
    setMarketSeries(null);
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
  const visibleSeries = useMemo(() => marketSeries ? selectChartRange(marketSeries, range) : null, [marketSeries, range]);
  const rangeLabel = CHART_RANGES.find((item) => item.value === range)!.label;
  const rangeHigh = visibleSeries?.ohlc?.length ? Math.max(...visibleSeries.ohlc.map((row) => row[3])) : undefined;
  const rangeLow = visibleSeries?.ohlc?.length ? Math.min(...visibleSeries.ohlc.map((row) => row[2])) : undefined;

  const rangeControls = (
    <div className="flex shrink-0 items-center gap-1 rounded-md bg-t-bg p-1" role="group" aria-label="行情周期">
      {CHART_RANGES.map((item) => (
        <button
          key={item.value}
          type="button"
          aria-pressed={range === item.value}
          onClick={() => setRange(item.value)}
          className={`min-h-8 flex-1 rounded px-3 text-xs font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-t-accent ${range === item.value ? 'bg-t-card text-t-text shadow-sm' : 'text-t-text2 hover:text-t-text'}`}
        >
          {item.label}
        </button>
      ))}
    </div>
  );

  const renderChart = (expanded = false) => loading ? (
    <div className="flex h-full items-center justify-center text-sm text-t-text2" role="status">
      <Loader2 className="mr-2 animate-spin" size={16} /> 正在加载真实行情…
    </div>
  ) : visibleSeries ? (
    <SmartChartRenderer
      block={expanded && visibleSeries.volume?.some((value) => value > 0) ? { ...block, type: 'price_volume' } : block}
      marketSeries={visibleSeries}
      fillContainer
      showTitle={false}
      fullRange
    />
  ) : (
    <div className="flex h-full items-center justify-center">
      <EmptyState icon={ChartNoAxesCombined} message={symbol ? '真实行情暂不可用' : '选择标的后查看真实行情'} />
    </div>
  );

  return (
    <>
      <div className="h-full overflow-y-auto p-4">
        <div className="mb-3 flex items-center justify-between gap-2">
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
        {!loading && lastClose !== undefined && (
          <div className="mb-4 flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="num text-2xl font-semibold text-t-text">{formatPrice(lastClose)}</span>
            {dailyChange !== undefined && (
              <span className={`num text-sm font-medium ${dailyChange > 0 ? 'text-t-up' : dailyChange < 0 ? 'text-t-down' : 'text-t-text2'}`}>
                {dailyChange > 0 ? '+' : ''}{dailyChange.toFixed(2)}%
              </span>
            )}
            <span className="text-xs text-t-text2">最近收盘 · 当日涨跌</span>
          </div>
        )}
        {rangeControls}
        <div className="mt-3 aspect-[4/3] max-h-[340px] min-h-[240px] w-full" data-testid="context-chart-surface">
          {renderChart()}
        </div>
        {!loading && visibleSeries && (
          <div className="mt-4 border-t border-t-divider pt-4">
            <dl className="grid grid-cols-3 gap-3">
              <div>
                <dt className="text-xs text-t-text2">区间最高</dt>
                <dd className="num mt-1 text-sm font-medium text-t-text">{rangeHigh === undefined ? '—' : formatPrice(rangeHigh)}</dd>
              </div>
              <div>
                <dt className="text-xs text-t-text2">区间最低</dt>
                <dd className="num mt-1 text-sm font-medium text-t-text">{rangeLow === undefined ? '—' : formatPrice(rangeLow)}</dd>
              </div>
              <div>
                <dt className="text-xs text-t-text2">交易日</dt>
                <dd className="num mt-1 text-sm font-medium text-t-text">{visibleSeries.labels.length}</dd>
              </div>
            </dl>
            <p className="mt-3 text-xs leading-relaxed text-t-text2">
              {visibleSeries.labels[0]?.slice(0, 10)} 至 {visibleSeries.labels.at(-1)?.slice(0, 10)}
            </p>
          </div>
        )}
      </div>

      <Dialog
        open={isChartMaximized}
        onClose={() => setIsChartMaximized(false)}
        labelledBy="right-panel-chart-title"
        overlayClassName="!z-[70] !p-2 sm:!p-6"
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
                <p className="mt-1 text-xs text-t-text2">日线 · 近 {rangeLabel}</p>
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
          <div className="shrink-0 px-4 pt-3 sm:px-6">{rangeControls}</div>
          <div className="min-h-0 flex-1 overflow-hidden px-2 py-3 sm:px-5 sm:py-4">
            {renderChart(true)}
          </div>
        </div>
      </Dialog>
    </>
  );
}
