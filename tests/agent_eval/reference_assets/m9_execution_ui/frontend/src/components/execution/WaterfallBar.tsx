/**
 * WaterfallBar — 瀑布图里的单条 step bar（轨道 + 定位条 + hover 详情）。
 * 只负责渲染时间轴轨道与 bar；step 名称/耗时由 ParallelWaterfall 的行布局承载。
 */
import type { WaterfallBar as WaterfallBarData } from './waterfallLayout';
import {
  waterfallBarClass,
  waterfallStatusLabel,
  waterfallKindLabel,
  formatDuration,
} from './colorMaps';

interface WaterfallBarProps {
  bar: WaterfallBarData;
}

export function WaterfallBar({ bar }: WaterfallBarProps) {
  const { step, leftPercent, widthPercent } = bar;

  return (
    <div className="relative h-4 w-full group">
      {/* 时间轴轨道 */}
      <div className="absolute inset-0 rounded bg-slate-500/10" />

      {/* 定位 bar（原生调色板，支持 alpha） */}
      <div
        className={`absolute top-0 h-4 rounded border ${waterfallBarClass(step.kind, step.status)}`}
        style={{ left: `${leftPercent}%`, width: `${widthPercent}%` }}
        title={`${step.name} · ${waterfallKindLabel(step.kind)} · ${waterfallStatusLabel(step.status)} · ${formatDuration(step.durationMs)}`}
      />

      {/* hover tooltip（fin-panel/border 为 hex 变量，禁止加 alpha） */}
      <div className="pointer-events-none absolute z-30 left-2 bottom-full mb-1 hidden group-hover:block whitespace-nowrap rounded-md border border-fin-border bg-fin-panel px-2 py-1 text-[10px] shadow-lg">
        <div className="font-medium text-fin-text">{step.name}</div>
        <div className="text-fin-muted">
          {waterfallKindLabel(step.kind)} · {waterfallStatusLabel(step.status)} · {formatDuration(step.durationMs)}
        </div>
      </div>
    </div>
  );
}

export default WaterfallBar;
