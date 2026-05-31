/**
 * ParallelWaterfall — 并行执行泳道瀑布图（FinSight 指挥台核心亮点）。
 *
 * 按 parallel_group 把执行步骤分泳道，每个 step 一行水平 bar：
 *   - 起点对齐到组起点（同组并行步骤起点一致）
 *   - 宽度 ∝ 真实耗时（duration_ms）
 *   - 颜色区分 tool(amber) / agent(violet) + 状态
 * 一眼看出「哪些步骤并行、各自耗时多久、是否缓存/失败」。
 */
import { useMemo } from 'react';
import { Layers, GitBranch } from 'lucide-react';

import type { TimelineEvent } from '../../types/execution';
import { buildWaterfallLayout } from './waterfallLayout';
import { WaterfallBar } from './WaterfallBar';
import { waterfallDotClass, formatDuration } from './colorMaps';

interface ParallelWaterfallProps {
  timeline: TimelineEvent[];
  compact?: boolean;
}

export function ParallelWaterfall({ timeline, compact = false }: ParallelWaterfallProps) {
  const layout = useMemo(() => buildWaterfallLayout(timeline), [timeline]);

  if (!layout.hasData) {
    return (
      <div className="rounded-lg border border-fin-border bg-fin-card px-3 py-3 text-xs text-fin-muted">
        暂无并行执行步骤
      </div>
    );
  }

  const { lanes, totalSpanMs } = layout;

  return (
    <div className="rounded-lg border border-fin-border bg-fin-card">
      {/* 标题栏 */}
      <div className="flex items-center justify-between gap-2 px-3 py-2 border-b border-fin-border">
        <div className="flex items-center gap-1.5 text-xs text-fin-text-secondary">
          <Layers size={12} className="text-fin-primary" />
          并行执行瀑布
        </div>
        <div className="text-2xs text-fin-muted tabular-nums">
          总跨度 {formatDuration(totalSpanMs)}
        </div>
      </div>

      {/* 泳道 */}
      <div className={`px-3 py-2 ${compact ? 'max-h-56' : 'max-h-80'} overflow-y-auto`}>
        {lanes.map((lane) => (
          <div key={lane.group} className="mb-2 last:mb-0">
            {/* 泳道标题 */}
            <div className="flex items-center gap-1.5 mb-1 text-[10px] text-fin-text-secondary">
              <GitBranch size={10} className="text-fin-muted" />
              <span className="font-medium">
                {lane.group === '(serial)' ? '串行' : lane.group}
              </span>
              {lane.steps.length > 1 && (
                <span className="px-1 py-px rounded bg-fin-primary/10 text-fin-primary tabular-nums">
                  并行 ×{lane.steps.length}
                </span>
              )}
            </div>

            {/* 步骤行 */}
            <div className="space-y-1">
              {lane.steps.map((step) => {
                const bar = layout.bars.get(step.stepId);
                return (
                  <div key={step.stepId} className="flex items-center gap-2">
                    {/* 左：状态点 + 名称 */}
                    <div className="w-32 shrink-0 flex items-center gap-1.5 min-w-0">
                      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${waterfallDotClass(step.status)}`} />
                      <span className="truncate text-[11px] text-fin-text" title={step.name}>
                        {step.name}
                      </span>
                    </div>
                    {/* 中：bar 轨道 */}
                    <div className="flex-1 min-w-0">
                      {bar ? (
                        <WaterfallBar bar={bar} />
                      ) : (
                        <div className="h-4 rounded bg-slate-500/10" />
                      )}
                    </div>
                    {/* 右：耗时 */}
                    <div className="w-12 shrink-0 text-right text-[10px] text-fin-muted tabular-nums">
                      {formatDuration(step.durationMs)}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ))}

        {/* 时间刻度 */}
        <div className="flex items-center gap-2 mt-2 pt-1.5 border-t border-fin-border">
          <div className="w-32 shrink-0 text-[9px] text-fin-muted">时间轴</div>
          <div className="flex-1 flex justify-between text-[9px] text-fin-muted tabular-nums">
            <span>0</span>
            <span>{formatDuration(totalSpanMs / 2)}</span>
            <span>{formatDuration(totalSpanMs)}</span>
          </div>
          <div className="w-12 shrink-0" />
        </div>
      </div>
    </div>
  );
}

export default ParallelWaterfall;
