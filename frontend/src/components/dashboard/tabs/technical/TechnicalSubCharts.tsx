/**
 * TechnicalSubCharts - RSI & MACD time-series sub-charts.
 *
 * Renders two vertically stacked ECharts:
 * 1. RSI line with 70/30 overbought/oversold zones
 * 2. MACD line + Signal line + Histogram bars
 * Both share the same X-axis (dates).
 */
import { useMemo } from 'react';
import ReactECharts from 'echarts-for-react';

import { useChartTheme } from '../../../../hooks/useChartTheme';
import type { IndicatorSeries } from '../../../../types/dashboard';

// --- Props ---

interface TechnicalSubChartsProps {
  indicatorSeries?: IndicatorSeries | null;
}

// --- Component ---

export function TechnicalSubCharts({ indicatorSeries }: TechnicalSubChartsProps) {
  const theme = useChartTheme();

  // --- RSI Chart ---
  const rsiOption = useMemo(() => {
    if (!indicatorSeries || indicatorSeries.dates.length === 0) return null;

    const { dates, rsi } = indicatorSeries;
    // Filter to only non-null values count
    const hasData = rsi.some((v) => v != null);
    if (!hasData) return null;

    return {
      tooltip: {
        trigger: 'axis' as const,
        backgroundColor: theme.tooltipBackground,
        borderColor: theme.tooltipBorder,
        textStyle: { color: theme.tooltipText, fontSize: 11 },
        formatter: (params: Array<{ axisValue: string; value: number | null; marker: string; seriesName: string }>) => {
          const date = params[0]?.axisValue ?? '';
          const rsiVal = params[0]?.value;
          return `<div style="font-size:11px">${date}<br/>${params[0]?.marker ?? ''} RSI: ${rsiVal != null ? rsiVal.toFixed(1) : '—'}</div>`;
        },
      },
      grid: { left: 48, right: 16, top: 24, bottom: 24 },
      xAxis: {
        type: 'category' as const,
        data: dates,
        axisLine: { lineStyle: { color: theme.border } },
        axisLabel: { color: theme.muted, fontSize: 9, rotate: 0, interval: Math.floor(dates.length / 5) },
      },
      yAxis: {
        type: 'value' as const,
        min: 0,
        max: 100,
        axisLabel: { color: theme.muted, fontSize: 9 },
        splitLine: { lineStyle: { color: theme.grid, type: 'dashed' } },
      },
      series: [
        {
          name: 'RSI',
          type: 'line',
          data: rsi,
          smooth: true,
          showSymbol: false,
          lineStyle: { color: theme.primary, width: 1.5 },
          itemStyle: { color: theme.primary },
        },
      ],
      // Overbought/oversold zones via markLine
      visualMap: {
        show: false,
        pieces: [
          { min: 0, max: 30, color: theme.success },
          { min: 30, max: 70, color: theme.primary },
          { min: 70, max: 100, color: theme.danger },
        ],
        seriesIndex: 0,
        type: 'piecewise' as const,
      },
    };
  }, [indicatorSeries, theme]);

  // --- MACD Chart ---
  const macdOption = useMemo(() => {
    if (!indicatorSeries || indicatorSeries.dates.length === 0) return null;

    const { dates, macd, macd_signal, macd_histogram } = indicatorSeries;
    const hasData = macd.some((v) => v != null) || macd_signal.some((v) => v != null);
    if (!hasData) return null;

    return {
      tooltip: {
        trigger: 'axis' as const,
        backgroundColor: theme.tooltipBackground,
        borderColor: theme.tooltipBorder,
        textStyle: { color: theme.tooltipText, fontSize: 11 },
      },
      legend: {
        data: ['MACD', 'Signal', 'Histogram'],
        textStyle: { color: theme.muted, fontSize: 10 },
        top: 0,
        itemWidth: 12,
        itemHeight: 8,
      },
      grid: { left: 48, right: 16, top: 28, bottom: 24 },
      xAxis: {
        type: 'category' as const,
        data: dates,
        axisLine: { lineStyle: { color: theme.border } },
        axisLabel: { color: theme.muted, fontSize: 9, rotate: 0, interval: Math.floor(dates.length / 5) },
      },
      yAxis: {
        type: 'value' as const,
        axisLabel: { color: theme.muted, fontSize: 9 },
        splitLine: { lineStyle: { color: theme.grid, type: 'dashed' } },
      },
      series: [
        {
          name: 'MACD',
          type: 'line',
          data: macd,
          smooth: true,
          showSymbol: false,
          lineStyle: { color: theme.primary, width: 1.5 },
          itemStyle: { color: theme.primary },
        },
        {
          name: 'Signal',
          type: 'line',
          data: macd_signal,
          smooth: true,
          showSymbol: false,
          lineStyle: { color: theme.warning, width: 1.5 },
          itemStyle: { color: theme.warning },
        },
        {
          name: 'Histogram',
          type: 'bar',
          data: macd_histogram.map((v) => ({
            value: v,
            itemStyle: {
              color: v != null && v >= 0 ? theme.success : theme.danger,
              opacity: 0.7,
            },
          })),
          barMaxWidth: 6,
        },
      ],
    };
  }, [indicatorSeries, theme]);

  if (!rsiOption && !macdOption) {
    return (
      <div className="p-4 bg-fin-card rounded-xl border border-fin-border">
        <div className="text-xs font-medium text-fin-muted mb-3">RSI / MACD</div>
        <div className="text-sm text-fin-muted">暂无技术指标时间序列数据</div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {/* RSI Chart */}
      {rsiOption && (
        <div className="p-4 bg-fin-card rounded-xl border border-fin-border">
          <div className="text-xs font-medium text-fin-muted mb-2">
            RSI (14)
            <span className="ml-2 text-2xs text-fin-border">70 超买 / 30 超卖</span>
          </div>
          <ReactECharts
            option={rsiOption}
            style={{ width: '100%', height: 180 }}
            opts={{ renderer: 'svg' }}
            notMerge
            lazyUpdate
          />
        </div>
      )}

      {/* MACD Chart */}
      {macdOption && (
        <div className="p-4 bg-fin-card rounded-xl border border-fin-border">
          <div className="text-xs font-medium text-fin-muted mb-2">MACD (12, 26, 9)</div>
          <ReactECharts
            option={macdOption}
            style={{ width: '100%', height: 200 }}
            opts={{ renderer: 'svg' }}
            notMerge
            lazyUpdate
          />
        </div>
      )}
    </div>
  );
}

export default TechnicalSubCharts;
