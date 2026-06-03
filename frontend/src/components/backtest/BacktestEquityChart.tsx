/**
 * BacktestEquityChart - 回测收益曲线图。
 *
 * 数据来源：后端 BacktestEngine.run() 返回的 equity_curve
 * （结构 [{ time, equity, price, position }]，见 backend/services/backtest_engine.py）。
 * 主轴画组合净值折线，并把「持仓区间」用 markArea 视觉标注，
 * 同时叠加从净值序列推导出的最大回撤区间（峰值 -> 谷底）。
 */
import { useMemo } from 'react';
import ReactECharts from 'echarts-for-react';

import { useChartTheme } from '../../hooks/useChartTheme';

// --- Types ---

export interface EquityPoint {
  time: string;
  equity: number;
  price?: number;
  position?: number;
}

interface BacktestEquityChartProps {
  equityCurve: Array<Record<string, unknown>>;
  initialCash?: number;
}

// --- Helpers ---

/** 把后端原始 equity_curve 规范化为强类型点序列，过滤脏数据。 */
function normalizePoints(raw: Array<Record<string, unknown>>): EquityPoint[] {
  const points: EquityPoint[] = [];
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue;
    const equity = Number(item.equity);
    const time = String(item.time ?? '').trim();
    if (!time || !Number.isFinite(equity)) continue;
    points.push({
      time,
      equity,
      price: Number.isFinite(Number(item.price)) ? Number(item.price) : undefined,
      position: Number(item.position) > 0 ? 1 : 0,
    });
  }
  return points;
}

/**
 * 计算最大回撤区间：先定位回撤最深的谷底，再回溯到此前的净值峰值。
 * 返回 [峰值索引, 谷底索引]，无有效回撤时返回 null。
 */
function findMaxDrawdownRange(points: EquityPoint[]): [number, number] | null {
  if (points.length < 2) return null;
  let peak = points[0].equity;
  let peakIdx = 0;
  let worstDd = 0;
  let troughIdx = -1;
  let troughPeakIdx = 0;

  points.forEach((point, idx) => {
    if (point.equity > peak) {
      peak = point.equity;
      peakIdx = idx;
    }
    if (peak > 0) {
      const dd = (point.equity - peak) / peak;
      if (dd < worstDd) {
        worstDd = dd;
        troughIdx = idx;
        troughPeakIdx = peakIdx;
      }
    }
  });

  if (troughIdx <= troughPeakIdx) return null;
  return [troughPeakIdx, troughIdx];
}

/** 抽取持仓连续区间，用于 markArea 标注「持仓中」时段。 */
function buildPositionRanges(points: EquityPoint[]): Array<[number, number]> {
  const ranges: Array<[number, number]> = [];
  let start = -1;
  points.forEach((point, idx) => {
    if (point.position === 1 && start === -1) {
      start = idx;
    } else if (point.position !== 1 && start !== -1) {
      ranges.push([start, idx - 1]);
      start = -1;
    }
  });
  if (start !== -1) ranges.push([start, points.length - 1]);
  return ranges;
}

// --- Component ---

export function BacktestEquityChart({ equityCurve, initialCash }: BacktestEquityChartProps) {
  const theme = useChartTheme();

  const option = useMemo(() => {
    const points = normalizePoints(equityCurve);
    if (points.length < 2) return null;

    const dates = points.map((p) => p.time);
    const equities = points.map((p) => Number(p.equity.toFixed(2)));
    const baseline = Number.isFinite(Number(initialCash)) ? Number(initialCash) : points[0].equity;

    // 终值高于初始资金画涨色，低于画跌色。
    const lineColor = equities[equities.length - 1] >= baseline ? theme.success : theme.danger;

    const positionRanges = buildPositionRanges(points);
    const ddRange = findMaxDrawdownRange(points);

    // markArea：持仓区间（淡主色）+ 最大回撤区间（淡跌色）。
    const positionAreas = positionRanges.map(([from, to]) => [
      { xAxis: dates[from], itemStyle: { color: theme.primaryFaint } },
      { xAxis: dates[to] },
    ]);
    const drawdownAreas = ddRange
      ? [[
          { xAxis: dates[ddRange[0]], itemStyle: { color: theme.isDark ? 'rgba(247,79,92,0.12)' : 'rgba(239,68,68,0.10)' } },
          { xAxis: dates[ddRange[1]] },
        ]]
      : [];

    return {
      animation: false,
      grid: { top: 24, right: 16, bottom: 28, left: 56 },
      tooltip: {
        trigger: 'axis' as const,
        backgroundColor: theme.tooltipBackground,
        borderColor: theme.tooltipBorder,
        textStyle: { color: theme.tooltipText, fontSize: 11 },
        valueFormatter: (val: number) => (Number.isFinite(val) ? val.toLocaleString() : '-'),
      },
      xAxis: {
        type: 'category' as const,
        data: dates,
        boundaryGap: false,
        axisLine: { lineStyle: { color: theme.border } },
        axisLabel: { color: theme.muted, fontSize: 10, hideOverlap: true },
      },
      yAxis: {
        type: 'value' as const,
        scale: true,
        splitLine: { lineStyle: { color: theme.grid } },
        axisLabel: {
          color: theme.muted,
          fontSize: 10,
          formatter: (val: number) => (Math.abs(val) >= 1e4 ? `${(val / 1e4).toFixed(1)}w` : String(val)),
        },
      },
      series: [
        {
          name: '组合净值',
          type: 'line' as const,
          data: equities,
          smooth: true,
          showSymbol: false,
          lineStyle: { width: 1.6, color: lineColor },
          areaStyle: { color: lineColor, opacity: 0.1 },
          // 初始资金基准线
          markLine: {
            silent: true,
            symbol: 'none',
            lineStyle: { color: theme.muted, type: 'dashed' as const, width: 1 },
            label: { color: theme.muted, fontSize: 10, formatter: '初始资金' },
            data: [{ yAxis: Number(baseline.toFixed(2)) }],
          },
          markArea: {
            silent: true,
            data: [...positionAreas, ...drawdownAreas],
          },
        },
      ],
    };
  }, [equityCurve, initialCash, theme]);

  if (!option) {
    return (
      <div className="flex items-center justify-center rounded-lg border border-fin-border bg-fin-bg py-8 text-xs text-fin-muted">
        暂无可绘制的净值曲线数据
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-fin-border bg-fin-bg p-2">
      <div className="mb-1 flex items-center gap-3 px-1 text-2xs text-fin-muted">
        <span className="inline-flex items-center gap-1">
          <span className="inline-block h-2 w-3 rounded-sm bg-fin-primary/15" />
          持仓区间
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="inline-block h-2 w-3 rounded-sm border border-fin-danger" />
          最大回撤区间
        </span>
      </div>
      <ReactECharts
        option={option}
        style={{ width: '100%', height: 240 }}
        opts={{ renderer: 'svg' }}
        notMerge
        lazyUpdate
      />
    </div>
  );
}

export default BacktestEquityChart;
