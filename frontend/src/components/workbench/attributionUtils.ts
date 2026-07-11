import type {
  AttributionPositionInput,
  PortfolioSummaryResponse,
} from '../../api/contracts';


export function buildAttributionPositions(
  data: PortfolioSummaryResponse | null,
): AttributionPositionInput[] {
  const positions = data?.positions ?? [];
  if (positions.length === 0) return [];

  const marketValueTotal = positions.reduce(
    (sum, position) => sum + Math.max(0, Number(position.market_value) || 0),
    0,
  );
  if (marketValueTotal > 0) {
    return positions
      .filter((position) => position.ticker && position.market_value > 0)
      .map((position) => ({
        ticker: position.ticker.trim().toUpperCase(),
        weight: position.market_value / marketValueTotal,
      }));
  }

  const shareTotal = positions.reduce(
    (sum, position) => sum + Math.max(0, Number(position.shares) || 0),
    0,
  );
  if (shareTotal <= 0) return [];
  return positions
    .filter((position) => position.ticker && position.shares > 0)
    .map((position) => ({
      ticker: position.ticker.trim().toUpperCase(),
      weight: position.shares / shareTotal,
    }));
}
