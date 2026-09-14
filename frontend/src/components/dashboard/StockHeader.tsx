/**
 * StockHeader - Top header bar for the v2 dashboard.
 *
 * Displays the active stock symbol, display name, asset type badge,
 * live price with change data, and action buttons for watchlist toggle,
 * quick analysis, and report generation.
 */
import { Star } from 'lucide-react';

import { useDashboardStore } from '../../store/dashboardStore';
import type { SnapshotData, ChartPoint, ValuationData } from '../../types/dashboard';
import { formatMarketCapForMarket, formatPriceForMarket } from '../../utils/format';
import { Stat, useToast } from '../ui';
import { DashboardSourceBadge } from './DashboardSourceBadge';
import { MiniPriceChart } from './tabs/overview/MiniPriceChart';

// --- Props ---

interface StockHeaderProps {
  ticker: string;
  displayName: string;
  assetType: string;
  snapshot: SnapshotData;
  charts: Record<string, ChartPoint[]>;
  valuation?: ValuationData | null;
  loading?: boolean;
}

// --- Helpers ---

/** Derive the latest close price from chart data */
const getLastClose = (charts: Record<string, ChartPoint[]>): number | null => {
  const marketChart = charts?.market_chart;
  if (!Array.isArray(marketChart) || marketChart.length === 0) return null;
  const last = marketChart[marketChart.length - 1];
  return last?.close ?? last?.value ?? null;
};

const getPriceChange = (charts: Record<string, ChartPoint[]>): { value: number; text: string } | null => {
  const points = charts?.market_chart;
  if (!Array.isArray(points) || points.length < 2) return null;
  const current = points[points.length - 1]?.close ?? points[points.length - 1]?.value;
  const previous = points[points.length - 2]?.close ?? points[points.length - 2]?.value;
  if (typeof current !== 'number' || typeof previous !== 'number' || previous === 0) return null;
  const percent = ((current - previous) / previous) * 100;
  return { value: percent, text: `${Math.abs(percent).toFixed(2)}%` };
};

// --- Component ---

export function StockHeader({
  ticker,
  displayName,
  assetType,
  snapshot,
  charts,
  valuation,
  loading,
}: StockHeaderProps) {
  const {
    watchlist,
    addWatchItemApi,
    removeWatchItemApi,
  } = useDashboardStore();
  const { toast } = useToast();

  // Watchlist toggle state
  const isInWatchlist = watchlist.some(
    (w) => w.symbol.toUpperCase() === ticker.toUpperCase(),
  );

  const handleToggleWatchlist = async () => {
    try {
      if (isInWatchlist) {
        await removeWatchItemApi(ticker);
      } else {
        await addWatchItemApi(ticker);
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : '操作失败，请稍后重试';
      toast({
        type: 'error',
        title: '自选操作失败',
        message,
      });
    }
  };

  // Derive price from snapshot or chart fallback
  const closePrice = snapshot?.index_level ?? snapshot?.nav ?? getLastClose(charts);
  const marketCap = valuation?.market_cap ?? null;
  const priceChange = getPriceChange(charts);

  return (
    <div className="flex items-center justify-between gap-4 border-b border-t-border bg-t-surface px-5 py-3 shrink-0 max-lg:px-3 max-lg:flex-wrap max-lg:gap-2">
      {/* Left: Symbol info + Price */}
      <div className="flex items-center gap-4 min-w-0 max-lg:gap-2 max-md:w-full max-md:flex-col max-md:items-start">
        {/* Symbol + Name */}
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-sm font-semibold text-t-text truncate">{displayName || ticker}</span>
          <span className="text-2xs text-t-text3 bg-t-elevated px-2 py-0.5 rounded shrink-0 uppercase">
            {assetType}
          </span>
        </div>

        {/* Price + Market Cap + Sparkline */}
        {loading ? (
          <div className="h-6 w-24 bg-fin-border rounded animate-pulse" />
        ) : (
          <div className="flex items-center gap-3 shrink-0 max-md:w-full max-md:min-w-0 max-md:flex-wrap max-md:shrink">
            {closePrice !== null && (
              <Stat
                label={ticker}
                value={formatPriceForMarket(closePrice, ticker)}
                change={priceChange?.value}
                changeText={priceChange?.text}
                className="min-w-[92px]"
              />
            )}
            {marketCap !== null && (
              <span className="num text-xs text-t-text3">
                {formatMarketCapForMarket(marketCap, ticker)}
              </span>
            )}
            <DashboardSourceBadge metaKey="market_chart" fallbackSource="yfinance" />
            {/* Mini sparkline */}
            {charts?.market_chart && charts.market_chart.length > 0 && (
              <div className="hidden sm:block">
                <MiniPriceChart data={charts.market_chart} />
              </div>
            )}
          </div>
        )}
      </div>

      {/* Right: Action buttons */}
      <div className="flex items-center gap-2 shrink-0">
        {/* Watchlist toggle */}
        <button
          type="button"
          onClick={handleToggleWatchlist}
          className={`p-2 rounded-lg border transition-colors ${
            isInWatchlist
              ? 'border-fin-warning/50 bg-fin-warning/10 text-fin-warning'
              : 'border-fin-border bg-fin-bg text-fin-muted hover:text-fin-warning hover:border-fin-warning/50'
          }`}
          title={isInWatchlist ? '从自选中移除' : '加入自选'}
        >
          <Star size={16} fill={isInWatchlist ? 'currentColor' : 'none'} />
        </button>

      </div>
    </div>
  );
}

export default StockHeader;
