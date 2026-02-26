import { useMemo } from 'react';

import type { PortfolioSummaryResponse, PortfolioSummaryPosition } from '../api/client';

// --- Public types ---

export interface PerformanceRow {
  ticker: string;
  currentPrice: number | null;
  dayChangePct: number | null;
  costBasis: number | null;
  marketValue: number;
  unrealizedPnl: number | null;
  unrealizedPnlPct: number | null;
  dayChange: number | null;
  shares: number;
  priceSource: string;
}

export interface PerformanceSummary {
  totalMarketValue: number;
  totalCost: number;
  totalPnl: number;
  totalPnlPct: number | null;
  totalDayChange: number;
  totalDayChangePct: number | null;
  positionCount: number;
  pricedCount: number;
}

export interface UsePortfolioPerformanceResult {
  rows: PerformanceRow[];
  summary: PerformanceSummary;
  isEmpty: boolean;
}

// --- Helpers ---

function buildRow(pos: PortfolioSummaryPosition): PerformanceRow {
  const avgCost = pos.avg_cost ?? null;
  const costBasis = avgCost !== null ? pos.shares * avgCost : null;
  const unrealizedPnl = pos.unrealized_pnl ?? null;
  const unrealizedPnlPct =
    costBasis !== null && costBasis > 0 && unrealizedPnl !== null
      ? (unrealizedPnl / costBasis) * 100
      : null;

  return {
    ticker: pos.ticker,
    currentPrice: pos.live_price ?? null,
    dayChangePct: pos.live_change_percent ?? null,
    costBasis,
    marketValue: pos.market_value,
    unrealizedPnl,
    unrealizedPnlPct,
    dayChange: pos.day_change ?? null,
    shares: pos.shares,
    priceSource: pos.price_source ?? 'unknown',
  };
}

function buildSummary(data: PortfolioSummaryResponse): PerformanceSummary {
  const totalPnlPct =
    data.total_cost > 0 ? (data.total_pnl / data.total_cost) * 100 : null;
  const totalDayChangePct =
    data.total_value > 0 && data.total_day_change !== undefined
      ? (data.total_day_change / (data.total_value - data.total_day_change)) * 100
      : null;

  return {
    totalMarketValue: data.total_value,
    totalCost: data.total_cost,
    totalPnl: data.total_pnl,
    totalPnlPct,
    totalDayChange: data.total_day_change ?? 0,
    totalDayChangePct,
    positionCount: data.count,
    pricedCount: data.priced_count ?? 0,
  };
}

// --- Hook ---

/**
 * Derives portfolio performance rows and summary from existing summary data.
 *
 * This hook does NOT fetch data itself — it transforms the response already
 * obtained by `usePortfolioSummary` into a presentation-friendly shape for
 * the PortfolioPerformance table.
 */
export function usePortfolioPerformance(
  data: PortfolioSummaryResponse | null,
): UsePortfolioPerformanceResult {
  const rows = useMemo<PerformanceRow[]>(() => {
    if (!data?.positions?.length) return [];
    return data.positions.map(buildRow);
  }, [data]);

  const summary = useMemo<PerformanceSummary>(() => {
    if (!data) {
      return {
        totalMarketValue: 0,
        totalCost: 0,
        totalPnl: 0,
        totalPnlPct: null,
        totalDayChange: 0,
        totalDayChangePct: null,
        positionCount: 0,
        pricedCount: 0,
      };
    }
    return buildSummary(data);
  }, [data]);

  return {
    rows,
    summary,
    isEmpty: rows.length === 0,
  };
}
