/**
 * RebalanceCompareView -- 调仓前后配置对比视图。
 *
 * 左右并排展示调仓前/后的权重饼图，以及差异汇总表格。
 * 仅展示已接受的操作变更（pending/rejected 的操作保持原权重）。
 */
import { useMemo } from 'react';
import ReactECharts from 'echarts-for-react';

import { useChartTheme } from '../../../hooks/useChartTheme.ts';
import type { RebalanceAction } from '../../../types/dashboard.ts';
import type { ActionDecisionMap } from '../../../hooks/useRebalanceWorkflow.ts';

interface RebalanceCompareViewProps {
  actions: readonly RebalanceAction[];
  decisions: ActionDecisionMap;
}

interface WeightEntry {
  readonly ticker: string;
  readonly weight: number;
}

// === 计算调仓后权重 ===

function computeAfterWeights(
  actions: readonly RebalanceAction[],
  decisions: ActionDecisionMap,
): { before: readonly WeightEntry[]; after: readonly WeightEntry[] } {
  const before: WeightEntry[] = [];
  const after: WeightEntry[] = [];

  for (const action of actions) {
    before.push({ ticker: action.ticker, weight: action.current_weight });

    const isAccepted = decisions[action.ticker] === 'accepted';
    after.push({
      ticker: action.ticker,
      weight: isAccepted ? action.target_weight : action.current_weight,
    });
  }

  // 按权重降序排列
  const sortDesc = (a: WeightEntry, b: WeightEntry) => b.weight - a.weight;
  return {
    before: [...before].sort(sortDesc),
    after: [...after].sort(sortDesc),
  };
}

// === 饼图配置 ===

function buildPieOption(
  entries: readonly WeightEntry[],
  title: string,
  theme: ReturnType<typeof useChartTheme>,
) {
  const filtered = entries.filter((e) => e.weight > 0);
  return {
    title: {
      text: title,
      left: 'center',
      top: 0,
      textStyle: { color: theme.muted, fontSize: 11, fontWeight: 500 },
    },
    tooltip: {
      trigger: 'item' as const,
      backgroundColor: theme.tooltipBackground,
      borderColor: theme.tooltipBorder,
      textStyle: { color: theme.tooltipText, fontSize: 11 },
      formatter: (params: { name: string; value: number; percent: number }) =>
        `<b>${params.name}</b><br/>权重: ${params.value.toFixed(1)}%`,
    },
    series: [
      {
        type: 'pie',
        radius: ['40%', '70%'],
        center: ['50%', '58%'],
        avoidLabelOverlap: true,
        itemStyle: { borderRadius: 4, borderColor: theme.tooltipBackground, borderWidth: 1 },
        label: {
          show: filtered.length <= 8,
          color: theme.textSecondary,
          fontSize: 9,
          formatter: '{b}\n{d}%',
        },
        emphasis: {
          label: { show: true, fontSize: 11, fontWeight: 'bold' },
        },
        data: filtered.map((e) => ({
          name: e.ticker,
          value: Number(e.weight.toFixed(1)),
        })),
      },
    ],
  };
}

// === 差异表格行 ===

interface DiffRow {
  readonly ticker: string;
  readonly before: number;
  readonly after: number;
  readonly delta: number;
  readonly accepted: boolean;
}

function computeDiffRows(
  actions: readonly RebalanceAction[],
  decisions: ActionDecisionMap,
): readonly DiffRow[] {
  return [...actions]
    .sort((a, b) => a.priority - b.priority)
    .map((action) => {
      const accepted = decisions[action.ticker] === 'accepted';
      const afterWeight = accepted
        ? action.target_weight
        : action.current_weight;
      return {
        ticker: action.ticker,
        before: action.current_weight,
        after: afterWeight,
        delta: afterWeight - action.current_weight,
        accepted,
      };
    });
}

// === 组件 ===

export function RebalanceCompareView({
  actions,
  decisions,
}: RebalanceCompareViewProps) {
  const theme = useChartTheme();

  const { before, after } = useMemo(
    () => computeAfterWeights(actions, decisions),
    [actions, decisions],
  );

  const beforeOption = useMemo(
    () => buildPieOption(before, '调仓前', theme),
    [before, theme],
  );

  const afterOption = useMemo(
    () => buildPieOption(after, '调仓后', theme),
    [after, theme],
  );

  const diffRows = useMemo(
    () => computeDiffRows(actions, decisions),
    [actions, decisions],
  );

  const acceptedCount = diffRows.filter((r) => r.accepted).length;

  return (
    <div className="space-y-3">
      {/* 饼图对比 */}
      <div className="grid grid-cols-2 gap-2">
        <div className="bg-fin-card/50 rounded-lg border border-fin-border/50 p-2">
          <ReactECharts
            option={beforeOption}
            style={{ width: '100%', height: 180 }}
            opts={{ renderer: 'svg' }}
            notMerge
            lazyUpdate
          />
        </div>
        <div className="bg-fin-card/50 rounded-lg border border-fin-border/50 p-2">
          <ReactECharts
            option={afterOption}
            style={{ width: '100%', height: 180 }}
            opts={{ renderer: 'svg' }}
            notMerge
            lazyUpdate
          />
        </div>
      </div>

      {/* 统计摘要 */}
      <div className="text-center text-2xs text-fin-muted">
        已接受 {acceptedCount} / {diffRows.length} 项操作
      </div>

      {/* 差异表格 */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-fin-border text-fin-muted">
              <th className="text-left py-1.5 px-2 font-medium">代码</th>
              <th className="text-right py-1.5 px-2 font-medium">调仓前</th>
              <th className="text-right py-1.5 px-2 font-medium">调仓后</th>
              <th className="text-right py-1.5 px-2 font-medium">变动</th>
              <th className="text-center py-1.5 px-2 font-medium">状态</th>
            </tr>
          </thead>
          <tbody>
            {diffRows.map((row) => (
              <tr
                key={row.ticker}
                className={`border-b border-fin-border/30 ${
                  row.accepted ? '' : 'opacity-50'
                }`}
              >
                <td className="py-1.5 px-2 font-semibold text-fin-text">
                  {row.ticker}
                </td>
                <td className="py-1.5 px-2 text-right text-fin-text-secondary">
                  {row.before.toFixed(1)}%
                </td>
                <td className="py-1.5 px-2 text-right text-fin-text">
                  {row.after.toFixed(1)}%
                </td>
                <td
                  className={`py-1.5 px-2 text-right font-medium ${
                    row.delta > 0
                      ? 'text-emerald-500'
                      : row.delta < 0
                        ? 'text-red-400'
                        : 'text-fin-muted'
                  }`}
                >
                  {row.delta >= 0 ? '+' : ''}
                  {row.delta.toFixed(1)}%
                </td>
                <td className="py-1.5 px-2 text-center">
                  <span
                    className={`inline-block w-2 h-2 rounded-full ${
                      row.accepted ? 'bg-emerald-500' : 'bg-fin-muted/40'
                    }`}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
