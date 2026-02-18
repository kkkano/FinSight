/**
 * StockHeader - Top header bar for the v2 dashboard.
 *
 * Displays the active stock symbol, display name, asset type badge,
 * live price with change data, and action buttons for watchlist toggle,
 * quick analysis, and report generation.
 */
import { FileText, Loader2, Star, Zap } from 'lucide-react';

import { useExecuteAgent } from '../../hooks/useExecuteAgent';
import { useDashboardStore } from '../../store/dashboardStore';
import type { SnapshotData, ChartPoint, ValuationData } from '../../types/dashboard';
import { useToast } from '../ui';
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

/** Format a number as compact currency (e.g. $1.2T, $340.5B) */
const formatMarketCap = (value: number | null | undefined): string => {
  if (value === null || value === undefined) return '--';
  if (value >= 1e12) return `$${(value / 1e12).toFixed(2)}T`;
  if (value >= 1e9) return `$${(value / 1e9).toFixed(2)}B`;
  if (value >= 1e6) return `$${(value / 1e6).toFixed(2)}M`;
  return `$${value.toLocaleString()}`;
};

/** Derive the latest close price from chart data */
const getLastClose = (charts: Record<string, ChartPoint[]>): number | null => {
  const marketChart = charts?.market_chart;
  if (!Array.isArray(marketChart) || marketChart.length === 0) return null;
  const last = marketChart[marketChart.length - 1];
  return last?.close ?? last?.value ?? null;
};

/** Format price with 2 decimal places */
const formatPrice = (value: number | null | undefined): string => {
  if (value === null || value === undefined) return '--';
  return value.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
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
    deepAnalysisIncludeDeepSearch,
    setDeepAnalysisIncludeDeepSearch,
  } = useDashboardStore();
  const { execute, isRunning, runId } = useExecuteAgent();
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

  const handleQuickAnalysis = () => {
    if (!ticker || isRunning) return;
    execute({
      query: `快速分析 ${ticker}`,
      tickers: [ticker],
      outputMode: 'brief',
      analysisDepth: 'quick',
      budget: 3,
      source: 'dashboard_header',
    });
  };

  const handleDeepAnalysis = () => {
    if (!ticker || isRunning) return;
    const includeDeepSearch = deepAnalysisIncludeDeepSearch;
    execute({
      query: includeDeepSearch
        ? `对 ${ticker} 做深度搜索，输出可追溯证据与关键结论`
        : `生成 ${ticker} 投资报告`,
      tickers: [ticker],
      outputMode: 'investment_report',
      analysisDepth: includeDeepSearch ? 'deep_research' : 'report',
      source: includeDeepSearch ? 'dashboard_deep_search' : 'dashboard_header',
    });
  };

  // Derive price from snapshot or chart fallback
  const closePrice = snapshot?.index_level ?? snapshot?.nav ?? getLastClose(charts);
  const marketCap = valuation?.market_cap ?? null;

  return (
    <div className="flex items-center justify-between gap-4 px-5 py-3 bg-fin-card border-b border-fin-border shrink-0 max-lg:px-3 max-lg:flex-wrap max-lg:gap-2">
      {/* Left: Symbol info + Price */}
      <div className="flex items-center gap-4 min-w-0 max-lg:gap-2">
        {/* Symbol + Name */}
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-lg font-bold text-fin-text truncate">{displayName || ticker}</span>
          <span className="text-2xs text-fin-muted bg-fin-bg-secondary px-2 py-0.5 rounded shrink-0 uppercase">
            {assetType}
          </span>
        </div>

        {/* Price + Market Cap + Sparkline */}
        {loading ? (
          <div className="h-6 w-24 bg-fin-border rounded animate-pulse" />
        ) : (
          <div className="flex items-center gap-3 shrink-0">
            {closePrice !== null && (
              <span className="text-lg font-semibold text-fin-text tabular-nums">
                ${formatPrice(closePrice)}
              </span>
            )}
            {marketCap !== null && (
              <span className="text-xs text-fin-muted">
                {formatMarketCap(marketCap)}
              </span>
            )}
            {/* Mini sparkline */}
            {charts?.market_chart && charts.market_chart.length > 0 && (
              <MiniPriceChart data={charts.market_chart} />
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

        {/* Quick Analysis */}
        <button
          type="button"
          onClick={handleQuickAnalysis}
          disabled={isRunning}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg border border-fin-border text-fin-muted hover:text-fin-primary hover:border-fin-primary/50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isRunning && runId ? (
            <Loader2 size={12} className="animate-spin" />
          ) : (
            <Zap size={12} />
          )}
          快速分析
        </button>

        {/* Deep analysis toggle + action */}
        <label className="flex items-center gap-1.5 px-2 py-1 text-2xs text-fin-muted border border-fin-border rounded-lg">
          <input
            type="checkbox"
            className="accent-fin-primary"
            checked={deepAnalysisIncludeDeepSearch}
            onChange={(event) => setDeepAnalysisIncludeDeepSearch(event.target.checked)}
          />
          含 deepsearch
        </label>
        <button
          type="button"
          onClick={handleDeepAnalysis}
          disabled={isRunning}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg border border-fin-primary/40 bg-fin-primary/10 text-fin-primary hover:bg-fin-primary/20 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isRunning && runId ? (
            <Loader2 size={12} className="animate-spin" />
          ) : (
            <FileText size={12} />
          )}
          深度分析
        </button>
      </div>
    </div>
  );
}

export default StockHeader;
