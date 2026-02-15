/**
 * BollingerVolumeCard - Bollinger Bands + Volume analysis.
 *
 * Shows Bollinger bands upper/middle/lower values with current price position.
 * Volume comparison: average vs today.
 */
import type { TechnicalData } from '../../../../types/dashboard';

// --- Props ---

interface BollingerVolumeCardProps {
  technicals?: TechnicalData | null;
}

// --- Helpers ---

const fmtPrice = (v: number | null | undefined): string => {
  if (v === null || v === undefined) return '--';
  return v.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
};

const fmtVolume = (v: number | null | undefined): string => {
  if (v === null || v === undefined) return '--';
  if (v >= 1e9) return `${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return v.toLocaleString();
};

function getBollingerPosition(
  close: number | null | undefined,
  upper: number | null | undefined,
  lower: number | null | undefined,
): { position: string; pct: number } {
  if (close == null || upper == null || lower == null) {
    return { position: '--', pct: 50 };
  }
  const range = upper - lower;
  if (range <= 0) return { position: '--', pct: 50 };

  const pct = ((close - lower) / range) * 100;

  let position: string;
  if (pct > 80) position = '上轨附近 (超买区)';
  else if (pct > 60) position = '中上区间';
  else if (pct > 40) position = '中轨附近';
  else if (pct > 20) position = '中下区间';
  else position = '下轨附近 (超卖区)';

  return { position, pct: Math.max(0, Math.min(100, pct)) };
}

// --- Component ---

export function BollingerVolumeCard({ technicals }: BollingerVolumeCardProps) {
  const upper = technicals?.bollinger_upper;
  const middle = technicals?.bollinger_middle;
  const lower = technicals?.bollinger_lower;
  const close = technicals?.close;
  const avgVolume = technicals?.avg_volume;

  const { position, pct } = getBollingerPosition(close, upper, lower);

  return (
    <div className="p-4 bg-fin-card rounded-xl border border-fin-border">
      <div className="text-xs font-medium text-fin-muted mb-3">布林带 & 成交量</div>

      {/* Bollinger Bands */}
      <div className="mb-4">
        <div className="text-2xs font-medium text-fin-text-secondary mb-2">布林带 (20,2)</div>

        <div className="grid grid-cols-3 gap-3 mb-3">
          <div className="flex flex-col">
            <span className="text-2xs text-fin-muted">上轨</span>
            <span className="text-sm text-fin-danger tabular-nums">{fmtPrice(upper)}</span>
          </div>
          <div className="flex flex-col">
            <span className="text-2xs text-fin-muted">中轨</span>
            <span className="text-sm text-fin-text tabular-nums">{fmtPrice(middle)}</span>
          </div>
          <div className="flex flex-col">
            <span className="text-2xs text-fin-muted">下轨</span>
            <span className="text-sm text-fin-success tabular-nums">{fmtPrice(lower)}</span>
          </div>
        </div>

        {/* Position indicator */}
        <div className="mb-1.5">
          <div className="flex items-center justify-between text-2xs text-fin-muted mb-1">
            <span>下轨</span>
            <span>{position}</span>
            <span>上轨</span>
          </div>
          <div className="relative h-2 bg-fin-border rounded-full">
            <div
              className="absolute top-0 h-2 bg-gradient-to-r from-fin-success via-fin-warning to-fin-danger rounded-full opacity-30"
              style={{ width: '100%' }}
            />
            <div
              className="absolute -top-0.5 w-3 h-3 bg-fin-primary rounded-full border-2 border-fin-card"
              style={{ left: `calc(${pct}% - 6px)` }}
            />
          </div>
        </div>
      </div>

      {/* Volume */}
      <div>
        <div className="text-2xs font-medium text-fin-text-secondary mb-2">成交量</div>
        <div className="grid grid-cols-2 gap-3">
          <div className="flex flex-col">
            <span className="text-2xs text-fin-muted">平均成交量</span>
            <span className="text-sm text-fin-text tabular-nums">{fmtVolume(avgVolume)}</span>
          </div>
          <div className="flex flex-col">
            <span className="text-2xs text-fin-muted">带宽</span>
            <span className="text-sm text-fin-text tabular-nums">
              {upper != null && lower != null && middle != null && middle !== 0
                ? `${(((upper - lower) / middle) * 100).toFixed(1)}%`
                : '--'}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

export default BollingerVolumeCard;
