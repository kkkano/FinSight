/**
 * BacktestTradesTable - 回测逐笔成交记录表。
 *
 * 数据来源：后端 BacktestEngine.run() 返回的 trades
 * （结构 [{ type: 'buy'|'sell', time, price, shares, fee, pnl? }]）。
 * 卖出行展示该笔平仓盈亏，涨绿跌红。
 */

interface BacktestTradesTableProps {
  trades: Array<Record<string, unknown>>;
}

/** 数字格式化，非法值返回占位符。 */
function fmtNum(value: unknown, digits = 2): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return '-';
  return n.toLocaleString(undefined, { maximumFractionDigits: digits });
}

export function BacktestTradesTable({ trades }: BacktestTradesTableProps) {
  if (!Array.isArray(trades) || trades.length === 0) {
    return (
      <div className="rounded-lg border border-fin-border bg-fin-bg py-6 text-center text-xs text-fin-muted">
        本次回测无成交记录
      </div>
    );
  }

  return (
    <div className="max-h-64 overflow-auto rounded-lg border border-fin-border">
      <table className="w-full min-w-[480px] text-xs">
        <thead className="sticky top-0 bg-fin-card">
          <tr className="text-fin-muted">
            <th className="px-2 py-1.5 text-left font-medium">方向</th>
            <th className="px-2 py-1.5 text-left font-medium">日期</th>
            <th className="px-2 py-1.5 text-right font-medium">价格</th>
            <th className="px-2 py-1.5 text-right font-medium">数量</th>
            <th className="px-2 py-1.5 text-right font-medium">手续费</th>
            <th className="px-2 py-1.5 text-right font-medium">盈亏</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((trade, idx) => {
            const isBuy = String(trade.type) === 'buy';
            const pnl = trade.pnl;
            const hasPnl = pnl !== null && pnl !== undefined && Number.isFinite(Number(pnl));
            const pnlPositive = Number(pnl) >= 0;
            return (
              <tr key={`trade-${idx}`} className="border-t border-fin-border/60">
                <td className="px-2 py-1.5">
                  <span
                    className={`rounded border bg-fin-bg px-1.5 py-0.5 text-2xs font-semibold ${
                      isBuy ? 'border-fin-success text-fin-success' : 'border-fin-danger text-fin-danger'
                    }`}
                  >
                    {isBuy ? '买入' : '卖出'}
                  </span>
                </td>
                <td className="px-2 py-1.5 text-fin-text-secondary">{String(trade.time ?? '-')}</td>
                <td className="px-2 py-1.5 text-right text-fin-text">{fmtNum(trade.price)}</td>
                <td className="px-2 py-1.5 text-right text-fin-text-secondary">{fmtNum(trade.shares, 4)}</td>
                <td className="px-2 py-1.5 text-right text-fin-muted">{fmtNum(trade.fee)}</td>
                <td className="px-2 py-1.5 text-right">
                  {hasPnl ? (
                    <span className={pnlPositive ? 'text-fin-success' : 'text-fin-danger'}>
                      {pnlPositive ? '+' : ''}
                      {fmtNum(pnl)}
                    </span>
                  ) : (
                    <span className="text-fin-muted">-</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default BacktestTradesTable;
