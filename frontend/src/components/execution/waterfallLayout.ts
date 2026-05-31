/**
 * waterfallLayout — 把 executionStore 的 timeline 事件聚合成「并行泳道瀑布图」布局。
 *
 * 纯函数、可单测。核心职责：
 *   1. 把同一 stepId 的 step_start / step_done 配对成一个 WaterfallStep
 *      （startMs 取 step_start 时间，durationMs 取 step_done 精确耗时）
 *   2. 按 parallel_group 分泳道（同组的并行步骤起点对齐）
 *   3. 计算每个 step bar 的 left% / width%（相对全局时间轴 origin → maxEnd）
 *
 * 设计要点（见真实抓包 skill_stream_1088.txt）：
 *   - step 时间戳精度仅到秒，同组并行 step 的 start 同秒 → left 自然对齐到组起点；
 *     宽度一律用 step_done.duration_ms（精确，如 s1=544 / s6=1317 / s3=2357ms），
 *     所以同组 bar 起点对齐、宽度反映各自真实耗时。
 */
import type { TimelineEvent } from '../../types/execution';

export type WaterfallStatus = 'pending' | 'running' | 'done' | 'cached' | 'skipped' | 'error';

export interface WaterfallStep {
  stepId: string;
  name: string;
  kind: string; // tool / agent / step
  parallelGroup: string | null;
  startMs: number | null; // epoch ms（来自 step_start.timestamp）
  durationMs: number | null; // 来自 step_done.duration_ms
  status: WaterfallStatus;
}

export interface WaterfallLane {
  group: string; // parallel_group 值，null 归一为 '(serial)'
  steps: WaterfallStep[];
}

export interface WaterfallBar {
  step: WaterfallStep;
  leftPercent: number;
  widthPercent: number;
}

export interface WaterfallLayout {
  lanes: WaterfallLane[];
  bars: Map<string, WaterfallBar>; // stepId → bar 布局
  originMs: number | null;
  totalSpanMs: number;
  hasData: boolean;
}

const SERIAL_LANE = '(serial)';
const MIN_BAR_WIDTH_PERCENT = 1.5;
const MIN_DURATION_MS = 50;

/** 从 timeline 聚合出每个 step 的执行信息（同 stepId 的 start/done 配对）。 */
export function extractWaterfallSteps(timeline: TimelineEvent[]): WaterfallStep[] {
  const map = new Map<string, WaterfallStep>();

  for (const ev of timeline) {
    const stepId = ev.stepId;
    if (!stepId) continue;
    if (ev.eventType !== 'step_start' && ev.eventType !== 'step_done' && ev.eventType !== 'step_error') {
      continue;
    }

    const existing: WaterfallStep = map.get(stepId) ?? {
      stepId,
      name: ev.name ?? stepId,
      kind: ev.kind ?? 'step',
      parallelGroup: ev.parallelGroup ?? null,
      startMs: null,
      durationMs: null,
      status: 'pending',
    };

    const tsMs = Date.parse(ev.timestamp);

    if (ev.eventType === 'step_start') {
      if (Number.isFinite(tsMs)) existing.startMs = existing.startMs ?? tsMs;
      if (existing.status === 'pending') existing.status = 'running';
    } else if (ev.eventType === 'step_done') {
      if (typeof ev.durationMs === 'number' && Number.isFinite(ev.durationMs)) {
        existing.durationMs = ev.durationMs;
      }
      existing.status = ev.cached
        ? 'cached'
        : ev.skipped
          ? 'skipped'
          : ev.status === 'error' || ev.status === 'failed'
            ? 'error'
            : 'done';
    } else {
      existing.status = 'error';
    }

    // 后到的事件可能字段更全，补齐 name/kind/parallelGroup
    if (ev.name) existing.name = ev.name;
    if (ev.kind) existing.kind = ev.kind;
    if (ev.parallelGroup != null) existing.parallelGroup = ev.parallelGroup;

    map.set(stepId, existing);
  }

  return [...map.values()];
}

/** 组内最早 startMs（用于泳道排序）。 */
function laneStartMs(lane: WaterfallLane): number {
  let min = Number.POSITIVE_INFINITY;
  for (const s of lane.steps) {
    if (s.startMs != null && s.startMs < min) min = s.startMs;
  }
  return min;
}

/** 按 parallel_group 分泳道，泳道按起点升序、组内按起点升序。 */
export function groupWaterfallLanes(steps: WaterfallStep[]): WaterfallLane[] {
  const laneMap = new Map<string, WaterfallStep[]>();
  for (const s of steps) {
    const key = s.parallelGroup ?? SERIAL_LANE;
    const arr = laneMap.get(key) ?? [];
    arr.push(s);
    laneMap.set(key, arr);
  }

  const lanes: WaterfallLane[] = [...laneMap.entries()].map(([group, arr]) => ({
    group,
    steps: [...arr].sort(
      (a, b) => (a.startMs ?? Number.POSITIVE_INFINITY) - (b.startMs ?? Number.POSITIVE_INFINITY),
    ),
  }));

  lanes.sort((a, b) => laneStartMs(a) - laneStartMs(b));
  return lanes;
}

/** 主入口：timeline → 完整瀑布布局。 */
export function buildWaterfallLayout(timeline: TimelineEvent[]): WaterfallLayout {
  const steps = extractWaterfallSteps(timeline);
  const lanes = groupWaterfallLanes(steps);

  let originMs: number | null = null;
  let maxEndMs = 0;
  for (const s of steps) {
    if (s.startMs == null) continue;
    originMs = originMs == null ? s.startMs : Math.min(originMs, s.startMs);
    const dur = Math.max(s.durationMs ?? MIN_DURATION_MS, MIN_DURATION_MS);
    maxEndMs = Math.max(maxEndMs, s.startMs + dur);
  }

  const totalSpanMs = originMs != null ? Math.max(maxEndMs - originMs, 1) : 1;

  const bars = new Map<string, WaterfallBar>();
  for (const s of steps) {
    if (s.startMs == null || originMs == null) continue;
    const barStartMs = s.startMs - originMs;
    const barDurMs = Math.max(s.durationMs ?? MIN_DURATION_MS, MIN_DURATION_MS);
    const leftPercent = Math.max(0, Math.min(100, (barStartMs / totalSpanMs) * 100));
    const rawWidth = Math.max((barDurMs / totalSpanMs) * 100, MIN_BAR_WIDTH_PERCENT);
    // 限制 bar 不越过轨道右边界（left + width <= 100）
    const widthPercent = Math.min(rawWidth, Math.max(MIN_BAR_WIDTH_PERCENT, 100 - leftPercent));
    bars.set(s.stepId, { step: s, leftPercent, widthPercent });
  }

  return {
    lanes,
    bars,
    originMs,
    totalSpanMs,
    hasData: steps.length > 0,
  };
}
