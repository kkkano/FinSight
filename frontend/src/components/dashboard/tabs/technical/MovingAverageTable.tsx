/**
 * MovingAverageTable - Moving average indicators table.
 *
 * Rows: MA5/10/20/50/100/200/EMA12/EMA26
 * Columns: Value + Signal (Buy/Sell based on close vs MA)
 */
import type { TechnicalData } from '../../../../types/dashboard';

// --- Props ---

interface MovingAverageTableProps {
  technicals?: TechnicalData | null;
}

// --- Types ---

interface MARow {
  label: string;
  value: number | null | undefined;
}

type MASignal = 'buy' | 'sell' | 'neutral';

// --- Helpers ---

const fmtPrice = (v: number | null | undefined): string => {
  if (v === null || v === undefined) return '--';
  return v.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
};

function getSignal(close: number | null | undefined, ma: number | null | undefined): MASignal {
  if (close == null || ma == null) return 'neutral';
  return close > ma ? 'buy' : 'sell';
}

const SIGNAL_DISPLAY: Record<MASignal, { label: string; className: string }> = {
  buy: { label: '买入', className: 'text-fin-success' },
  sell: { label: '卖出', className: 'text-fin-danger' },
  neutral: { label: '--', className: 'text-fin-muted' },
};

function buildRows(technicals: TechnicalData | null | undefined): MARow[] {
  if (!technicals) return [];
  return [
    { label: 'MA5', value: technicals.ma5 },
    { label: 'MA10', value: technicals.ma10 },
    { label: 'MA20', value: technicals.ma20 },
    { label: 'MA50', value: technicals.ma50 },
    { label: 'MA100', value: technicals.ma100 },
    { label: 'MA200', value: technicals.ma200 },
    { label: 'EMA12', value: technicals.ema12 },
    { label: 'EMA26', value: technicals.ema26 },
  ];
}

// --- Component ---

export function MovingAverageTable({ technicals }: MovingAverageTableProps) {
  const rows = buildRows(technicals);
  const close = technicals?.close;

  if (rows.length === 0) {
    return (
      <div className="p-4 bg-fin-card rounded-xl border border-fin-border">
        <div className="text-xs font-medium text-fin-muted mb-3">均线指标</div>
        <div className="text-sm text-fin-muted">--</div>
      </div>
    );
  }

  return (
    <div className="p-4 bg-fin-card rounded-xl border border-fin-border">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-medium text-fin-muted">均线指标</span>
        {close != null && (
          <span className="text-2xs text-fin-text-secondary">
            当前价: <span className="text-fin-text font-medium tabular-nums">{fmtPrice(close)}</span>
          </span>
        )}
      </div>

      <table className="w-full text-2xs">
        <thead>
          <tr className="border-b border-fin-border">
            <th className="text-left py-2 text-fin-muted font-medium">指标</th>
            <th className="text-right py-2 text-fin-muted font-medium">数值</th>
            <th className="text-right py-2 text-fin-muted font-medium">信号</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const signal = getSignal(close, row.value);
            const display = SIGNAL_DISPLAY[signal];
            return (
              <tr key={row.label} className="border-b border-fin-border/50 last:border-b-0">
                <td className="py-2 text-fin-text font-medium">{row.label}</td>
                <td className="text-right py-2 tabular-nums text-fin-text">{fmtPrice(row.value)}</td>
                <td className={`text-right py-2 font-medium ${display.className}`}>
                  {display.label}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default MovingAverageTable;
