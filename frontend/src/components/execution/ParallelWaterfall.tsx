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
import { executionSubjectLabel } from './timelineUtils';

interface ParallelWaterfallProps {
  timeline: TimelineEvent[];
  compact?: boolean;
}

export function ParallelWaterfall({ timeline, compact = false }: ParallelWaterfallProps) {
  const layout = useMemo(() => buildWaterfallLayout(timeline), [timeline]);

  if (!layout.hasData) {
    return (
      <div className="py-3 text-sm text-t-text2">
        暂无并行执行步骤
      </div>
    );
  }

  const { lanes, totalSpanMs } = layout;

  return (
    <section className="border-t border-t-divider pt-4">
      {/* 标题栏 */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 text-sm font-medium text-t-text">
          <Layers size={16} className="text-t-text2" />
          并行执行瀑布
        </h3>
        <div className="num text-xs text-t-text2">
          总跨度 {formatDuration(totalSpanMs)}
        </div>
      </div>

      {/* 泳道 */}
      <div className="mt-4 space-y-4">
        {lanes.map((lane) => (
          <div key={lane.group}>
            {/* 泳道标题 */}
            <div className="mb-2 flex flex-wrap items-start gap-1.5 text-xs text-t-text2">
              <GitBranch size={14} className="mt-0.5 shrink-0" />
              <span className="min-w-0 break-all font-medium">
                {lane.group === '(serial)' ? '串行步骤' : lane.group}
              </span>
              {lane.steps.length > 1 && (
                <span className="num shrink-0 text-t-accent">
                  并行 ×{lane.steps.length}
                </span>
              )}
            </div>

            {/* 步骤行 */}
            <div className={compact ? 'space-y-3' : 'space-y-4'}>
              {lane.steps.map((step) => {
                const bar = layout.bars.get(step.stepId);
                return (
                  <div key={step.stepId}>
                    {/* 左：状态点 + 名称 */}
                    <div className="mb-1.5 flex items-start justify-between gap-3">
                      <div className="flex min-w-0 items-start gap-1.5">
                        <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${waterfallDotClass(step.status)}`} />
                        <span className="min-w-0 break-words text-xs text-t-text" title={step.name}>
                          {executionSubjectLabel(step.name)}
                        </span>
                      </div>
                      <span className="num shrink-0 text-xs text-t-text2">{formatDuration(step.durationMs)}</span>
                    </div>
                    {/* 中：bar 轨道 */}
                    <div className="min-w-0">
                      {bar ? (
                        <WaterfallBar bar={bar} />
                      ) : (
                        <div className="h-4 rounded bg-slate-500/10" />
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ))}

        {/* 时间刻度 */}
        <div className="border-t border-t-divider pt-3">
          <div className="num flex justify-between text-xs text-t-text2">
            <span>0</span>
            <span>{formatDuration(totalSpanMs / 2)}</span>
            <span>{formatDuration(totalSpanMs)}</span>
          </div>
        </div>
      </div>
    </section>
  );
}

export default ParallelWaterfall;
