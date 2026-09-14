/**
 * SupportResistanceChart - K-line candlestick chart with support/resistance levels.
 *
 * Replaces the old CSS bar version with a real ECharts candlestick chart.
 * Support levels shown as green horizontal lines, resistance as red.
 * DataZoom allows zooming into specific date ranges.
 */
import { useMemo } from 'react';
import ReactECharts from 'echarts-for-react';

import { useChartTheme, type ChartTheme } from '../../../../hooks/useChartTheme';
import type { ChartPoint, TechnicalData } from '../../../../types/dashboard';
import { DashboardSourceBadge } from '../../DashboardSourceBadge';
import { applyPredictionOverlay, STATUS_SUFFIX } from '../../../charts/PredictionOverlay';
import type { PredictionOverlay } from '../../../../types/chartPrediction';

// --- Props ---

interface SupportResistanceChartProps {
  technicals?: TechnicalData | null;
  marketChart?: ChartPoint[];
  marketAsOf?: string;
  predictionOverlay?: PredictionOverlay | null;
}

// --- Helpers ---

interface MarkLineEntry {
  yAxis: number;
  lineStyle: { color: string; type: string; width: number };
  label: { formatter: string; position: string; fontSize: number };
}

const buildLevelLines = (
  levels: number[],
  type: 'support' | 'resistance',
  theme: ChartTheme,
): MarkLineEntry[] =>
  levels.map((value) => ({
    yAxis: value,
    lineStyle: {
      color: type === 'support' ? theme.success : theme.danger,
      type: 'dashed',
      width: 1.5,
    },
    label: {
      formatter: `${type === 'support' ? 'S' : 'R'} ${value.toFixed(2)}`,
      position: 'insideEndTop',
      fontSize: 10,
    },
  }));

const formatDate = (point: ChartPoint): string => {
  if (point.time) {
    const d = new Date(point.time * 1000);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  }
  return point.period ?? '';
};

// --- Component ---

function formatAsOf(metaAsOf: string | undefined, marketChart: ChartPoint[] | undefined): string {
  const raw = String(metaAsOf ?? '').trim();
  if (raw) return `截至 ${raw}`;
  const last = marketChart?.[marketChart.length - 1];
  if (last?.time) return `截至 ${formatDate(last)}`;
  if (last?.period) return `截至 ${last.period}`;
  return '截至时间未知';
}

export function SupportResistanceChart({
  technicals,
  marketChart,
  marketAsOf,
  predictionOverlay,
}: SupportResistanceChartProps) {
  const theme = useChartTheme();

  const option = useMemo(() => {
    if (!marketChart || marketChart.length === 0) return null;

    const slice = marketChart;

    const dates = slice.map(formatDate);
    const ohlc = slice.map((p) => [p.open ?? 0, p.close ?? 0, p.low ?? 0, p.high ?? 0]);
    const volumes = slice.map((p) => p.volume ?? 0);

    const supportLevels = technicals?.support_levels ?? [];
    const resistanceLevels = technicals?.resistance_levels ?? [];

    const marketOption = {
      animation: true,
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        backgroundColor: theme.tooltipBackground,
        borderColor: theme.tooltipBorder,
        textStyle: { color: theme.tooltipText, fontSize: 11 },
      },
      grid: [
        { left: 60, right: 16, top: 24, bottom: 80 },
        { left: 60, right: 16, top: '72%', bottom: 32 },
      ],
      xAxis: [
        {
          type: 'category',
          data: dates,
          axisLine: { lineStyle: { color: theme.border } },
          axisLabel: { color: theme.muted, fontSize: 10, rotate: 0 },
          splitLine: { show: false },
          gridIndex: 0,
        },
        {
          type: 'category',
          data: dates,
          gridIndex: 1,
          axisLabel: { show: false },
          axisLine: { show: false },
          axisTick: { show: false },
        },
      ],
      yAxis: [
        {
          type: 'value',
          scale: true,
          gridIndex: 0,
          axisLabel: { color: theme.muted, fontSize: 10 },
          splitLine: { lineStyle: { color: theme.grid, type: 'dashed' } },
        },
        {
          type: 'value',
          scale: true,
          gridIndex: 1,
          axisLabel: { show: false },
          splitLine: { show: false },
        },
      ],
      dataZoom: [
        {
          type: 'inside',
          xAxisIndex: [0, 1],
          start: 60,
          end: 100,
        },
        {
          type: 'slider',
          xAxisIndex: [0, 1],
          bottom: 8,
          height: 18,
          borderColor: theme.border,
          fillerColor: theme.sliderFiller,
          handleStyle: { color: theme.primary },
          textStyle: { color: theme.muted, fontSize: 10 },
        },
      ],
      series: [
        {
          name: 'K线',
          type: 'candlestick',
          data: ohlc,
          xAxisIndex: 0,
          yAxisIndex: 0,
          itemStyle: {
            color: theme.success,
            color0: theme.danger,
            borderColor: theme.success,
            borderColor0: theme.danger,
          },
          markLine: {
            symbol: 'none',
            silent: true,
            data: [
              ...buildLevelLines(supportLevels, 'support', theme),
              ...buildLevelLines(resistanceLevels, 'resistance', theme),
            ],
          },
        },
        {
          name: '成交量',
          type: 'bar',
          data: volumes,
          xAxisIndex: 1,
          yAxisIndex: 1,
          itemStyle: {
            color: theme.primarySoft,
          },
          barMaxWidth: 6,
        },
      ],
    };
    return applyPredictionOverlay(marketOption, predictionOverlay ?? null, dates);
  }, [marketChart, predictionOverlay, technicals, theme]);

  const asOfText = formatAsOf(marketAsOf, marketChart);

  if (!option) {
    return (
      <div
        className="p-4 bg-fin-card rounded-lg border border-fin-border"
        data-testid="dashboard-primary-candlestick"
      >
        <div className="mb-3 flex items-center justify-between gap-3">
          <div>
            <div className="text-xs font-medium text-fin-muted">日线快照 · 支撑/阻力位</div>
            <div className="mt-0.5 text-2xs text-fin-muted">{asOfText}</div>
          </div>
          <DashboardSourceBadge metaKey="market_chart" />
        </div>
        <div className="text-sm text-fin-muted">暂无K线数据</div>
      </div>
    );
  }

  return (
    <div
      className="p-4 bg-fin-card rounded-lg border border-fin-border"
      data-testid="dashboard-primary-candlestick"
    >
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs font-medium text-fin-muted">
            <span>日线快照 · K线图 · 支撑/阻力位</span>
            {predictionOverlay && (
              <span className="text-t-warning">AI 标注 · {STATUS_SUFFIX[predictionOverlay.status]}</span>
            )}
          </div>
          <div className="mt-0.5 text-2xs text-fin-muted">{asOfText}</div>
        </div>
        <DashboardSourceBadge metaKey="market_chart" />
      </div>
      <ReactECharts
        option={option}
        style={{ width: '100%', height: 360 }}
        opts={{ renderer: (marketChart?.length ?? 0) > 200 ? 'canvas' : 'svg' }}
        notMerge
        lazyUpdate
      />
    </div>
  );
}

export default SupportResistanceChart;
