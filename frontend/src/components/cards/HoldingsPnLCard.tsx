/**
 * HoldingsPnLCard - 持仓盈亏卡片
 *
 * 展示每个持仓的代码、股数、成本价、现价、盈亏金额和百分比。
 * 底部汇总行展示组合总览。盈利绿色、亏损红色。
 * 报价未加载时显示骨架屏。
 */
import { Card } from '../ui/Card';
import type { PortfolioPnLResult, PositionPnL } from '../../types/dashboard';

interface HoldingsPnLCardProps {
  /** 盈亏计算结果（来自 usePortfolioPnL） */
  pnlResult: PortfolioPnLResult;
  /** 报价是否正在加载 */
  loading?: boolean;
  /** 卡片标题 */
  title?: string;
}

/** 格式化货币金额，保留两位小数 */
const formatCurrency = (value: number): string => {
  const abs = Math.abs(value);
  const prefix = value < 0 ? '-' : '';
  if (abs >= 1e9) return `${prefix}$${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${prefix}$${(abs / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${prefix}$${abs.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  return `${prefix}$${abs.toFixed(2)}`;
};

/** 格式化百分比 */
const formatPercent = (value: number): string => {
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toFixed(2)}%`;
};

/** 根据盈亏值返回颜色类名 */
const pnlColorClass = (value: number | null): string => {
  if (value === null) return 'text-fin-muted';
  if (value > 0) return 'text-green-500';
  if (value < 0) return 'text-red-500';
  return 'text-fin-text';
};

/** 单行持仓骨架屏 */
function SkeletonRow() {
  return (
    <tr className="animate-pulse">
      <td className="py-2 px-2"><div className="h-4 bg-fin-border rounded w-12" /></td>
      <td className="py-2 px-2 text-right"><div className="h-4 bg-fin-border rounded w-10 ml-auto" /></td>
      <td className="py-2 px-2 text-right"><div className="h-4 bg-fin-border rounded w-14 ml-auto" /></td>
      <td className="py-2 px-2 text-right"><div className="h-4 bg-fin-border rounded w-14 ml-auto" /></td>
      <td className="py-2 px-2 text-right"><div className="h-4 bg-fin-border rounded w-16 ml-auto" /></td>
      <td className="py-2 px-2 text-right"><div className="h-4 bg-fin-border rounded w-14 ml-auto" /></td>
    </tr>
  );
}

/** 持仓行组件 */
function PositionRow({ position }: { readonly position: PositionPnL }) {
  const {
    symbol,
    shares,
    avgCost,
    currentPrice,
    unrealizedPnL,
    pnlPercent,
  } = position;

  const pnlColor = pnlColorClass(unrealizedPnL);

  return (
    <tr className="border-t border-fin-border/50 hover:bg-fin-hover/30 transition-colors">
      {/* 代码 */}
      <td className="py-2.5 px-2 text-sm font-medium text-fin-text">
        {symbol}
      </td>
      {/* 股数 */}
      <td className="py-2.5 px-2 text-sm text-fin-text text-right tabular-nums">
        {shares.toLocaleString()}
      </td>
      {/* 成本价 */}
      <td className="py-2.5 px-2 text-sm text-fin-muted text-right tabular-nums">
        {avgCost > 0 ? `$${avgCost.toFixed(2)}` : '--'}
      </td>
      {/* 现价 */}
      <td className="py-2.5 px-2 text-sm text-fin-text text-right tabular-nums">
        {currentPrice !== null ? `$${currentPrice.toFixed(2)}` : '--'}
      </td>
      {/* 盈亏金额 */}
      <td className={`py-2.5 px-2 text-sm text-right tabular-nums font-medium ${pnlColor}`}>
        {unrealizedPnL !== null ? formatCurrency(unrealizedPnL) : '--'}
      </td>
      {/* 盈亏百分比 */}
      <td className={`py-2.5 px-2 text-sm text-right tabular-nums font-medium ${pnlColor}`}>
        {pnlPercent !== null ? formatPercent(pnlPercent) : '--'}
      </td>
    </tr>
  );
}

export function HoldingsPnLCard({
  pnlResult,
  loading = false,
  title = '持仓盈亏',
}: HoldingsPnLCardProps) {
  const {
    positions,
    totalValue,
    totalCost,
    totalPnL,
    totalPnLPercent,
    hasPartialData,
  } = pnlResult;

  const totalPnLColor = pnlColorClass(totalPnL);

  // 骨架屏状态
  if (loading) {
    return (
      <Card className="rounded-xl p-4">
        <div className="h-5 bg-fin-border rounded w-24 mb-4 animate-pulse" />
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="text-xs text-fin-muted">
                <th className="py-2 px-2 font-medium">代码</th>
                <th className="py-2 px-2 font-medium text-right">股数</th>
                <th className="py-2 px-2 font-medium text-right">成本</th>
                <th className="py-2 px-2 font-medium text-right">现价</th>
                <th className="py-2 px-2 font-medium text-right">盈亏</th>
                <th className="py-2 px-2 font-medium text-right">盈亏%</th>
              </tr>
            </thead>
            <tbody>
              {Array.from({ length: 4 }, (_, i) => (
                <SkeletonRow key={i} />
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    );
  }

  // 无持仓
  if (positions.length === 0) {
    return (
      <Card className="rounded-xl p-4">
        <h3 className="text-sm font-semibold text-fin-text mb-3">{title}</h3>
        <div className="h-32 flex items-center justify-center text-fin-muted text-sm">
          暂无持仓数据
        </div>
      </Card>
    );
  }

  return (
    <Card className="rounded-xl p-4">
      <h3 className="text-sm font-semibold text-fin-text mb-3">{title}</h3>

      {/* 持仓表格 */}
      <div className="overflow-x-auto">
        <table className="w-full text-left">
          <thead>
            <tr className="text-xs text-fin-muted border-b border-fin-border">
              <th className="py-2 px-2 font-medium">代码</th>
              <th className="py-2 px-2 font-medium text-right">股数</th>
              <th className="py-2 px-2 font-medium text-right">成本</th>
              <th className="py-2 px-2 font-medium text-right">现价</th>
              <th className="py-2 px-2 font-medium text-right">盈亏</th>
              <th className="py-2 px-2 font-medium text-right">盈亏%</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((pos) => (
              <PositionRow key={pos.symbol} position={pos} />
            ))}
          </tbody>
        </table>
      </div>

      {/* 汇总行 */}
      <div className="mt-3 pt-3 border-t border-fin-border">
        <div className="flex items-center justify-between rounded-lg bg-fin-bg-secondary/50 px-3 py-2.5">
          <div className="flex items-center gap-4">
            <span className="text-xs text-fin-muted">组合总计</span>
            <span className="text-sm text-fin-text tabular-nums">
              市值 {formatCurrency(totalValue)}
            </span>
            <span className="text-sm text-fin-muted tabular-nums">
              成本 {formatCurrency(totalCost)}
            </span>
          </div>
          <div className="flex items-center gap-3">
            <span className={`text-sm font-semibold tabular-nums ${totalPnLColor}`}>
              {formatCurrency(totalPnL)}
            </span>
            <span className={`text-sm font-semibold tabular-nums ${totalPnLColor}`}>
              {formatPercent(totalPnLPercent)}
            </span>
          </div>
        </div>

        {/* 部分数据缺失提示 */}
        {hasPartialData && (
          <p className="mt-2 text-xs text-fin-muted">
            * 部分持仓缺少实时报价，汇总仅包含有报价的持仓
          </p>
        )}
      </div>
    </Card>
  );
}

export default HoldingsPnLCard;
