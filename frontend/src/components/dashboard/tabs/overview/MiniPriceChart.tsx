/**
 * MiniPriceChart - Sparkline area chart for StockHeader.
 *
 * Renders a minimal 120px-high area chart from market_chart OHLCV data.
 * Color follows price change direction: green for up, red for down.
 * Uses useChartTheme() for theme-aware colors.
 */
import { useMemo } from 'react';
import ReactECharts from 'echarts-for-react';

import { useChartTheme } from '../../../../hooks/useChartTheme';
import type { ChartPoint } from '../../../../types/dashboard';

// --- Props ---

interface MiniPriceChartProps {
  data: ChartPoint[];
}

// --- Component ---

export function MiniPriceChart({ data }: MiniPriceChartProps) {
  const theme = useChartTheme();

  const option = useMemo(() => {
    if (!data || data.length === 0) return null;

    const closes = data.map((p) => p.close ?? p.value ?? 0);
    const dates = data.map((p) =>
      p.time ? new Date(p.time * 1000).toLocaleDateString() : (p.period ?? ''),
    );

    // Determine direction: compare last close to first close
    const first = closes[0] ?? 0;
    const last = closes[closes.length - 1] ?? 0;
    const isUp = last >= first;
    const lineColor = isUp ? theme.success : theme.danger;

    return {
      animation: false,
      grid: { top: 4, right: 0, bottom: 4, left: 0 },
      xAxis: {
        type: 'category' as const,
        show: false,
        data: dates,
        boundaryGap: false,
      },
      yAxis: {
        type: 'value' as const,
        show: false,
        min: 'dataMin',
        max: 'dataMax',
      },
      series: [
        {
          type: 'line' as const,
          data: closes,
          smooth: true,
          showSymbol: false,
          lineStyle: { width: 1.5, color: lineColor },
          areaStyle: { color: lineColor, opacity: 0.12 },
        },
      ],
      tooltip: { show: false },
    };
  }, [data, theme]);

  if (!option) return null;

  return (
    <ReactECharts
      option={option}
      style={{ width: 160, height: 48 }}
      opts={{ renderer: 'svg' }}
      notMerge
      lazyUpdate
    />
  );
}

export default MiniPriceChart;
