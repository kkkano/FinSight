/**
 * PeerComparisonTable - Full comparison table for peer companies.
 *
 * Renders an HTML table with 10+ columns including valuation metrics,
 * profitability, growth, and dividend data. Current stock row is highlighted.
 */
import type { PeerMetrics } from '../../../../types/dashboard.ts';

interface PeerComparisonTableProps {
  peers: PeerMetrics[];
  subjectSymbol: string;
}

function fmt(value: number | null | undefined, decimals = 1, suffix = ''): string {
  if (value == null) return '--';
  return `${value.toFixed(decimals)}${suffix}`;
}

function fmtPct(value: number | null | undefined): string {
  if (value == null) return '--';
  return `${(value * 100).toFixed(1)}%`;
}

function fmtCap(value: number | null | undefined): string {
  if (value == null) return '--';
  if (value >= 1e12) return `${(value / 1e12).toFixed(1)}T`;
  if (value >= 1e9) return `${(value / 1e9).toFixed(1)}B`;
  if (value >= 1e6) return `${(value / 1e6).toFixed(1)}M`;
  return value.toFixed(0);
}

const COLUMNS: { key: string; label: string; align?: string }[] = [
  { key: 'symbol', label: '代码' },
  { key: 'name', label: '名称' },
  { key: 'market_cap', label: '市值', align: 'right' },
  { key: 'trailing_pe', label: 'P/E', align: 'right' },
  { key: 'price_to_book', label: 'P/B', align: 'right' },
  { key: 'ev_to_ebitda', label: 'EV/EBITDA', align: 'right' },
  { key: 'net_margin', label: '净利率', align: 'right' },
  { key: 'roe', label: 'ROE', align: 'right' },
  { key: 'revenue_growth', label: '营收增长', align: 'right' },
  { key: 'dividend_yield', label: '股息率', align: 'right' },
  { key: 'score', label: '评分', align: 'right' },
];

function getCellValue(peer: PeerMetrics, key: string): string {
  switch (key) {
    case 'symbol': return peer.symbol;
    case 'name': return peer.name;
    case 'market_cap': return fmtCap(peer.market_cap);
    case 'trailing_pe': return fmt(peer.trailing_pe);
    case 'price_to_book': return fmt(peer.price_to_book);
    case 'ev_to_ebitda': return fmt(peer.ev_to_ebitda);
    case 'net_margin': return fmtPct(peer.net_margin);
    case 'roe': return fmtPct(peer.roe);
    case 'revenue_growth': return fmtPct(peer.revenue_growth);
    case 'dividend_yield': return fmtPct(peer.dividend_yield);
    case 'score': return peer.score != null ? peer.score.toFixed(0) : '--';
    default: return '--';
  }
}

export function PeerComparisonTable({ peers, subjectSymbol }: PeerComparisonTableProps) {
  if (peers.length === 0) {
    return (
      <div className="flex items-center justify-center h-32 text-fin-muted text-sm">
        暂无同行对比数据
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="border-b border-fin-border">
            {COLUMNS.map((col) => (
              <th
                key={col.key}
                className={`px-3 py-2 text-xs font-medium text-fin-muted whitespace-nowrap ${
                  col.align === 'right' ? 'text-right' : 'text-left'
                }`}
              >
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {peers.map((peer) => {
            const isCurrent = peer.symbol.toUpperCase() === subjectSymbol.toUpperCase();
            return (
              <tr
                key={peer.symbol}
                className={`border-b border-fin-border/50 transition-colors ${
                  isCurrent
                    ? 'bg-fin-primary/5'
                    : 'hover:bg-fin-hover/40'
                }`}
              >
                {COLUMNS.map((col) => (
                  <td
                    key={col.key}
                    className={`px-3 py-2 whitespace-nowrap ${
                      col.align === 'right' ? 'text-right' : 'text-left'
                    } ${
                      col.key === 'symbol' && isCurrent
                        ? 'text-fin-primary font-semibold'
                        : 'text-fin-text'
                    }`}
                  >
                    {getCellValue(peer, col.key)}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default PeerComparisonTable;
