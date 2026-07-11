import type { PortfolioSummaryResponse } from '../../api/contracts';


const recalculateSummary = (
  current: PortfolioSummaryResponse,
  positions: PortfolioSummaryResponse['positions'],
): PortfolioSummaryResponse => {
  const totalValue = positions.reduce((sum, position) => sum + position.market_value, 0);
  const totalCost = positions.reduce((sum, position) => sum + position.cost_basis, 0);
  return {
    ...current,
    positions,
    count: positions.length,
    total_value: totalValue,
    total_cost: totalCost,
    total_pnl: totalValue - totalCost,
  };
};


export const upsertPortfolioSummaryPosition = (
  current: PortfolioSummaryResponse | undefined,
  ticker: string,
  shares: number,
  avgCost: number | null,
): PortfolioSummaryResponse | undefined => {
  if (!current) return current;
  const normalized = ticker.trim().toUpperCase();
  const existing = current.positions.find((position) => position.ticker === normalized);
  const unitPrice = existing?.live_price
    ?? (existing && existing.shares > 0 ? existing.market_value / existing.shares : null)
    ?? avgCost
    ?? existing?.avg_cost
    ?? 0;
  const resolvedAvgCost = avgCost ?? existing?.avg_cost ?? null;
  const nextPosition = {
    ...(existing ?? {
      ticker: normalized,
      market_value: 0,
      cost_basis: 0,
    }),
    ticker: normalized,
    shares,
    avg_cost: resolvedAvgCost,
    market_value: shares * unitPrice,
    cost_basis: shares * (resolvedAvgCost ?? 0),
  };
  const positions = existing
    ? current.positions.map((position) => position.ticker === normalized ? nextPosition : position)
    : [...current.positions, nextPosition];
  return recalculateSummary(current, positions);
};


export const removePortfolioSummaryPosition = (
  current: PortfolioSummaryResponse | undefined,
  ticker: string,
): PortfolioSummaryResponse | undefined => {
  if (!current) return current;
  const normalized = ticker.trim().toUpperCase();
  return recalculateSummary(
    current,
    current.positions.filter((position) => position.ticker !== normalized),
  );
};
