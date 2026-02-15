/**
 * SupportResistanceChart - Support/resistance levels visual display.
 *
 * Shows support/resistance levels as horizontal bars with current price
 * position indicator. Uses a simple bar-based representation.
 */
import { useMemo } from 'react';

import type { TechnicalData } from '../../../../types/dashboard';

// --- Props ---

interface SupportResistanceChartProps {
  technicals?: TechnicalData | null;
}

// --- Helpers ---

const fmtPrice = (v: number): string =>
  v.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

interface LevelEntry {
  price: number;
  type: 'support' | 'resistance' | 'current';
  label: string;
}

function buildLevels(technicals: TechnicalData | null | undefined): LevelEntry[] {
  if (!technicals) return [];

  const entries: LevelEntry[] = [];

  // Add resistance levels (descending)
  const resistances = [...(technicals.resistance_levels ?? [])].sort((a, b) => b - a);
  resistances.forEach((price, idx) => {
    entries.push({ price, type: 'resistance', label: `R${idx + 1}` });
  });

  // Add current price
  if (technicals.close != null) {
    entries.push({ price: technicals.close, type: 'current', label: '当前价' });
  }

  // Add support levels (descending)
  const supports = [...(technicals.support_levels ?? [])].sort((a, b) => b - a);
  supports.forEach((price, idx) => {
    entries.push({ price, type: 'support', label: `S${idx + 1}` });
  });

  // Sort all by price descending
  return entries.sort((a, b) => b.price - a.price);
}

// --- Component ---

export function SupportResistanceChart({ technicals }: SupportResistanceChartProps) {
  const levels = useMemo(() => buildLevels(technicals), [technicals]);

  if (levels.length === 0) {
    return (
      <div className="p-4 bg-fin-card rounded-xl border border-fin-border">
        <div className="text-xs font-medium text-fin-muted mb-3">支撑/阻力位</div>
        <div className="text-sm text-fin-muted">--</div>
      </div>
    );
  }

  // Compute range for visual positioning
  const allPrices = levels.map((l) => l.price);
  const minPrice = Math.min(...allPrices);
  const maxPrice = Math.max(...allPrices);
  const range = maxPrice - minPrice || 1;

  return (
    <div className="p-4 bg-fin-card rounded-xl border border-fin-border">
      <div className="text-xs font-medium text-fin-muted mb-3">支撑/阻力位</div>

      {/* Legend */}
      <div className="flex items-center gap-4 mb-3 text-2xs">
        <div className="flex items-center gap-1.5">
          <span className="w-3 h-0.5 bg-fin-danger inline-block" />
          <span className="text-fin-muted">阻力位</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-3 h-0.5 bg-fin-success inline-block" />
          <span className="text-fin-muted">支撑位</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-3 h-0.5 bg-fin-primary inline-block" />
          <span className="text-fin-muted">当前价</span>
        </div>
      </div>

      {/* Level bars */}
      <div className="space-y-2">
        {levels.map((level, idx) => {
          const position = ((level.price - minPrice) / range) * 100;

          const colorMap = {
            resistance: 'bg-fin-danger',
            current: 'bg-fin-primary',
            support: 'bg-fin-success',
          } as const;

          const textColorMap = {
            resistance: 'text-fin-danger',
            current: 'text-fin-primary',
            support: 'text-fin-success',
          } as const;

          const isCurrent = level.type === 'current';

          return (
            <div key={`${level.type}-${idx}`} className="flex items-center gap-2">
              <span className={`text-2xs w-10 shrink-0 font-medium ${textColorMap[level.type]}`}>
                {level.label}
              </span>
              <div className="flex-1 relative h-4">
                <div className="absolute inset-0 bg-fin-border/30 rounded-full" />
                <div
                  className={`absolute top-0 h-4 rounded-full ${colorMap[level.type]} ${
                    isCurrent ? 'opacity-80' : 'opacity-40'
                  }`}
                  style={{ width: `${Math.max(4, position)}%` }}
                />
                {isCurrent && (
                  <div
                    className="absolute top-0 w-1 h-4 bg-fin-primary rounded"
                    style={{ left: `${position}%` }}
                  />
                )}
              </div>
              <span className={`text-2xs tabular-nums w-20 text-right shrink-0 ${textColorMap[level.type]} ${isCurrent ? 'font-semibold' : ''}`}>
                {fmtPrice(level.price)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default SupportResistanceChart;
