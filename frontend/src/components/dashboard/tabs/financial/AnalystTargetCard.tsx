/**
 * AnalystTargetCard - Analyst price target range + Buy/Hold/Sell ratio.
 *
 * Displays a horizontal range gauge showing analyst low/mean/high targets
 * with current price marker. Optional recommendation bar below.
 */
import { useMemo } from 'react';
import ReactECharts from 'echarts-for-react';

import { useChartTheme } from '../../../../hooks/useChartTheme';
import { CardInfoTip } from '../../../ui/CardInfoTip';
import type { AnalystTargets, RecommendationsSummary } from '../../../../types/dashboard';

// --- Props ---

interface AnalystTargetCardProps {
  targets?: AnalystTargets | null;
  recommendations?: RecommendationsSummary | null;
  currentPrice?: number | null;
}

// --- Component ---

export function AnalystTargetCard({ targets, recommendations, currentPrice }: AnalystTargetCardProps) {
  const theme = useChartTheme();

  // --- Recommendations bar ---
  const recBar = useMemo(() => {
    if (!recommendations) return null;
    const total =
      recommendations.strong_buy +
      recommendations.buy +
      recommendations.hold +
      recommendations.sell +
      recommendations.strong_sell;
    if (total === 0) return null;

    const segments = [
      { label: '强买', count: recommendations.strong_buy, color: theme.success },
      { label: '买入', count: recommendations.buy, color: '#22d3ee' },
      { label: '持有', count: recommendations.hold, color: theme.warning },
      { label: '卖出', count: recommendations.sell, color: '#f97316' },
      { label: '强卖', count: recommendations.strong_sell, color: theme.danger },
    ].filter((s) => s.count > 0);

    return { segments, total };
  }, [recommendations, theme]);

  // --- Target range chart ---
  const option = useMemo(() => {
    if (!targets) return null;
    const { low, mean, high } = targets;
    if (low == null && mean == null && high == null) return null;

    const minVal = Math.min(...[low, mean, high, currentPrice].filter((v): v is number => v != null)) * 0.95;
    const maxVal = Math.max(...[low, mean, high, currentPrice].filter((v): v is number => v != null)) * 1.05;

    const markPoints: Array<{ coord: [number, number]; symbol: string; symbolSize: number; itemStyle: { color: string }; label: { show: boolean; formatter: string; position: string; fontSize: number; color: string } }> = [];

    if (currentPrice != null) {
      markPoints.push({
        coord: [currentPrice, 0],
        symbol: 'triangle',
        symbolSize: 12,
        itemStyle: { color: theme.primary },
        label: {
          show: true,
          formatter: `当前 $${currentPrice.toFixed(1)}`,
          position: 'top',
          fontSize: 10,
          color: theme.primary,
        },
      });
    }

    return {
      tooltip: { show: false },
      grid: { left: 48, right: 48, top: 28, bottom: 16 },
      xAxis: {
        type: 'value' as const,
        min: minVal,
        max: maxVal,
        axisLabel: {
          color: theme.muted,
          fontSize: 9,
          formatter: (v: number) => `$${v.toFixed(0)}`,
        },
        splitLine: { lineStyle: { color: theme.grid, type: 'dashed' } },
      },
      yAxis: {
        type: 'value' as const,
        show: false,
        min: -1,
        max: 1,
      },
      series: [
        {
          type: 'line',
          data: [[low ?? minVal, 0], [high ?? maxVal, 0]],
          lineStyle: { color: theme.border, width: 8, cap: 'round' },
          showSymbol: false,
          markPoint: {
            data: [
              ...(low != null ? [{
                coord: [low, 0],
                symbol: 'diamond',
                symbolSize: 10,
                itemStyle: { color: theme.danger },
                label: { show: true, formatter: `$${low.toFixed(0)}`, position: 'bottom' as const, fontSize: 9, color: theme.danger },
              }] : []),
              ...(mean != null ? [{
                coord: [mean, 0],
                symbol: 'circle',
                symbolSize: 12,
                itemStyle: { color: theme.warning },
                label: { show: true, formatter: `均值 $${mean.toFixed(0)}`, position: 'bottom' as const, fontSize: 9, color: theme.warning },
              }] : []),
              ...(high != null ? [{
                coord: [high, 0],
                symbol: 'diamond',
                symbolSize: 10,
                itemStyle: { color: theme.success },
                label: { show: true, formatter: `$${high.toFixed(0)}`, position: 'bottom' as const, fontSize: 9, color: theme.success },
              }] : []),
              ...markPoints,
            ],
          },
        },
      ],
    };
  }, [targets, currentPrice, theme]);

  if (!option && !recBar) {
    return (
      <div className="p-4 bg-fin-card rounded-xl border border-fin-border">
        <div className="flex items-center gap-1 text-xs font-medium text-fin-muted mb-3">
          分析师目标价
          <CardInfoTip content="来源：yfinance 分析师目标价预测 + 评级分布" />
        </div>
        <div className="text-sm text-fin-muted">暂无分析师数据</div>
      </div>
    );
  }

  return (
    <div className="p-4 bg-fin-card rounded-xl border border-fin-border">
      <div className="flex items-center gap-1 text-xs font-medium text-fin-muted mb-2">
        分析师目标价
        <CardInfoTip content="来源：yfinance 分析师目标价预测 + 评级分布" />
      </div>

      {option && (
        <ReactECharts
          option={option}
          style={{ width: '100%', height: 100 }}
          opts={{ renderer: 'svg' }}
          notMerge
          lazyUpdate
        />
      )}

      {/* Recommendation ratio bar */}
      {recBar && (
        <div className="mt-3">
          <div className="text-2xs text-fin-muted mb-1.5">评级分布 ({recBar.total} 位分析师)</div>
          <div className="flex h-4 rounded-full overflow-hidden">
            {recBar.segments.map((seg) => (
              <div
                key={seg.label}
                className="flex items-center justify-center text-2xs text-white font-medium"
                style={{
                  width: `${(seg.count / recBar.total) * 100}%`,
                  backgroundColor: seg.color,
                  minWidth: seg.count > 0 ? 16 : 0,
                }}
                title={`${seg.label}: ${seg.count}`}
              >
                {seg.count > 0 ? seg.count : ''}
              </div>
            ))}
          </div>
          <div className="flex justify-between mt-1 text-2xs text-fin-muted">
            <span>买入</span>
            <span>卖出</span>
          </div>
        </div>
      )}
    </div>
  );
}

export default AnalystTargetCard;
