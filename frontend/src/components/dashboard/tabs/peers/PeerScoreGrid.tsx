/**
 * PeerScoreGrid - Grid of peer company score cards.
 *
 * Displays up to 6 company score cards with the current stock highlighted.
 */
import { useMemo } from 'react';

import type { PeerMetrics } from '../../../../types/dashboard.ts';

interface PeerScoreGridProps {
  peers: PeerMetrics[];
  subjectSymbol: string;
}

function formatMarketCap(value: number | null | undefined): string {
  if (value == null) return '--';
  if (value >= 1e12) return `${(value / 1e12).toFixed(1)}T`;
  if (value >= 1e9) return `${(value / 1e9).toFixed(1)}B`;
  if (value >= 1e6) return `${(value / 1e6).toFixed(1)}M`;
  return value.toFixed(0);
}

export function PeerScoreGrid({ peers, subjectSymbol }: PeerScoreGridProps) {
  const topPeers = useMemo(() => {
    // Sort by score descending, take top 6
    return [...peers]
      .sort((a, b) => (b.score ?? 0) - (a.score ?? 0))
      .slice(0, 6);
  }, [peers]);

  if (topPeers.length === 0) {
    return (
      <div className="flex items-center justify-center h-32 text-fin-muted text-sm">
        暂无同行数据
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
      {topPeers.map((peer) => {
        const isCurrent = peer.symbol.toUpperCase() === subjectSymbol.toUpperCase();
        return (
          <div
            key={peer.symbol}
            className={`rounded-lg border p-3 transition-colors ${
              isCurrent
                ? 'border-fin-primary bg-fin-primary/5'
                : 'border-fin-border bg-fin-card'
            }`}
          >
            <div className="flex items-center justify-between mb-2">
              <span className={`text-sm font-semibold ${isCurrent ? 'text-fin-primary' : 'text-fin-text'}`}>
                {peer.symbol}
              </span>
              {peer.score != null ? (
                <span className={`text-xs font-medium px-1.5 py-0.5 rounded ${
                  peer.score >= 70
                    ? 'bg-fin-success/10 text-fin-success'
                    : peer.score >= 40
                      ? 'bg-fin-warning/10 text-fin-warning'
                      : 'bg-fin-danger/10 text-fin-danger'
                }`}>
                  {peer.score.toFixed(0)}
                </span>
              ) : (
                <span className="text-xs text-fin-muted">--</span>
              )}
            </div>
            <div className="text-xs text-fin-muted truncate mb-1">{peer.name}</div>
            <div className="text-2xs text-fin-muted">
              市值 {formatMarketCap(peer.market_cap)}
            </div>
            {/* Score bar */}
            <div className="h-1 bg-fin-border rounded-full overflow-hidden mt-2">
              <div
                className={`h-full rounded-full transition-all duration-500 ${
                  isCurrent ? 'bg-fin-primary' : 'bg-fin-muted'
                }`}
                style={{ width: `${Math.min(peer.score ?? 0, 100)}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default PeerScoreGrid;
