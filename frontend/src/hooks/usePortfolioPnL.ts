/**
 * usePortfolioPnL - 投资组合盈亏（P&L）计算 Hook
 *
 * 接收持仓列表和实时报价，计算每个持仓的未实现盈亏及组合汇总。
 * 所有返回数据均为不可变对象，不会修改传入参数。
 */
import { useMemo } from 'react';
import type { PortfolioPosition, PositionPnL, PortfolioPnLResult } from '../types/dashboard';
import type { MarketQuote } from './useMarketQuotes';

/** 根据 symbol 在报价列表中查找对应价格 */
const findQuotePrice = (
  symbol: string,
  quotes: readonly MarketQuote[],
): number | null => {
  const upper = symbol.toUpperCase();
  const matched = quotes.find(
    (q) => q.label.toUpperCase() === upper,
  );
  if (matched?.price !== undefined && matched.price !== null) {
    return matched.price;
  }
  return null;
};

/** 计算单个持仓的盈亏 */
const computePositionPnL = (
  position: PortfolioPosition,
  quotes: readonly MarketQuote[],
): PositionPnL => {
  const { symbol, shares, avgCost } = position;
  const cost = avgCost ?? 0;
  const costBasis = cost * shares;
  const currentPrice = findQuotePrice(symbol, quotes);

  // 报价缺失时，盈亏相关字段返回 null
  if (currentPrice === null || cost <= 0) {
    return {
      symbol,
      shares,
      avgCost: cost,
      currentPrice,
      unrealizedPnL: null,
      pnlPercent: null,
      marketValue: currentPrice !== null ? currentPrice * shares : null,
      costBasis,
    };
  }

  const marketValue = currentPrice * shares;
  const unrealizedPnL = (currentPrice - cost) * shares;
  const pnlPercent = ((currentPrice - cost) / cost) * 100;

  return {
    symbol,
    shares,
    avgCost: cost,
    currentPrice,
    unrealizedPnL,
    pnlPercent,
    marketValue,
    costBasis,
  };
};

/**
 * 计算投资组合盈亏
 *
 * @param portfolioPositions - 持仓列表（symbol, shares, avgCost）
 * @param quotes - 实时报价列表（来自 useMarketQuotes）
 * @returns 不可变的 PortfolioPnLResult，包含各持仓明细和组合汇总
 */
export function usePortfolioPnL(
  portfolioPositions: readonly PortfolioPosition[],
  quotes: readonly MarketQuote[],
): PortfolioPnLResult {
  return useMemo(() => {
    // 无持仓时返回空结果
    if (portfolioPositions.length === 0) {
      return {
        positions: [],
        totalValue: 0,
        totalCost: 0,
        totalPnL: 0,
        totalPnLPercent: 0,
        hasPartialData: false,
      } as const satisfies PortfolioPnLResult;
    }

    // 逐个计算盈亏（不修改原始数据）
    const positions = portfolioPositions.map((pos) =>
      computePositionPnL(pos, quotes),
    );

    // 汇总：仅统计有报价且有成本的持仓
    let totalValue = 0;
    let totalCost = 0;
    let hasPartialData = false;

    for (const pos of positions) {
      if (pos.unrealizedPnL !== null && pos.marketValue !== null) {
        totalValue += pos.marketValue;
        totalCost += pos.costBasis;
      } else {
        hasPartialData = true;
      }
    }

    const totalPnL = totalValue - totalCost;
    const totalPnLPercent = totalCost > 0
      ? ((totalValue - totalCost) / totalCost) * 100
      : 0;

    return {
      positions: Object.freeze(positions),
      totalValue,
      totalCost,
      totalPnL,
      totalPnLPercent,
      hasPartialData,
    } as const satisfies PortfolioPnLResult;
  }, [portfolioPositions, quotes]);
}
