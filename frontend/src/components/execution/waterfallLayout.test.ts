import { describe, it, expect } from 'vitest';

import type { TimelineEvent } from '../../types/execution';
import {
  buildWaterfallLayout,
  extractWaterfallSteps,
  groupWaterfallLanes,
} from './waterfallLayout';

/** 构造 TimelineEvent 的便捷函数（值取自真实抓包 skill_stream_1088.txt）。 */
const mk = (over: Partial<TimelineEvent>): TimelineEvent => ({
  id: `${over.eventType}-${over.stepId}-${Math.random().toString(36).slice(2, 6)}`,
  timestamp: '2026-05-22T14:33:25Z',
  eventType: 'step_start',
  stage: 'executing',
  ...over,
});

/**
 * 模拟 NVDA valuation 的真实并行执行：
 *   task_1 组（tools，同秒并行）：s1=544ms、s6=1317ms、s3=2357ms（乱序完成）
 *   task_1_agents 组（agent，晚 3s 启动）：s8=900ms
 */
function buildFixtureTimeline(): TimelineEvent[] {
  return [
    mk({ eventType: 'step_start', stepId: 's1', kind: 'tool', name: 'get_stock_price', parallelGroup: 'task_1', timestamp: '2026-05-22T14:33:25Z' }),
    mk({ eventType: 'step_start', stepId: 's3', kind: 'tool', name: 'get_sec_company_facts_quarterly', parallelGroup: 'task_1', timestamp: '2026-05-22T14:33:25Z' }),
    mk({ eventType: 'step_start', stepId: 's6', kind: 'tool', name: 'get_technical_snapshot', parallelGroup: 'task_1', timestamp: '2026-05-22T14:33:25Z' }),
    mk({ eventType: 'step_done', stepId: 's1', kind: 'tool', name: 'get_stock_price', parallelGroup: 'task_1', durationMs: 544, status: 'done' }),
    mk({ eventType: 'step_done', stepId: 's6', kind: 'tool', name: 'get_technical_snapshot', parallelGroup: 'task_1', durationMs: 1317, status: 'done' }),
    mk({ eventType: 'step_done', stepId: 's3', kind: 'tool', name: 'get_sec_company_facts_quarterly', parallelGroup: 'task_1', durationMs: 2357, status: 'done' }),
    mk({ eventType: 'step_start', stepId: 's8', kind: 'agent', name: 'fundamental_agent', parallelGroup: 'task_1_agents', timestamp: '2026-05-22T14:33:28Z' }),
    mk({ eventType: 'step_done', stepId: 's8', kind: 'agent', name: 'fundamental_agent', parallelGroup: 'task_1_agents', durationMs: 900, status: 'done' }),
  ];
}

describe('extractWaterfallSteps', () => {
  it('把同 stepId 的 start/done 配对，duration 取自 step_done', () => {
    const steps = extractWaterfallSteps(buildFixtureTimeline());
    const byId = Object.fromEntries(steps.map((s) => [s.stepId, s]));

    expect(steps).toHaveLength(4);
    expect(byId.s1.durationMs).toBe(544);
    expect(byId.s3.durationMs).toBe(2357);
    expect(byId.s6.durationMs).toBe(1317);
    expect(byId.s1.status).toBe('done');
    expect(byId.s1.startMs).not.toBeNull();
    expect(byId.s8.kind).toBe('agent');
  });

  it('忽略无 stepId 的非 step 事件', () => {
    const steps = extractWaterfallSteps([
      mk({ eventType: 'pipeline_stage', stepId: undefined }),
      mk({ eventType: 'plan_ready', stepId: undefined }),
    ]);
    expect(steps).toHaveLength(0);
  });

  it('cached / skipped / error 状态正确判定', () => {
    const steps = extractWaterfallSteps([
      mk({ eventType: 'step_start', stepId: 'c1', parallelGroup: 'g' }),
      mk({ eventType: 'step_done', stepId: 'c1', cached: true, durationMs: 10 }),
      mk({ eventType: 'step_start', stepId: 'e1', parallelGroup: 'g' }),
      mk({ eventType: 'step_done', stepId: 'e1', status: 'error', durationMs: 5 }),
    ]);
    const byId = Object.fromEntries(steps.map((s) => [s.stepId, s]));
    expect(byId.c1.status).toBe('cached');
    expect(byId.e1.status).toBe('error');
  });
});

describe('groupWaterfallLanes', () => {
  it('按 parallelGroup 分泳道，泳道按起点升序', () => {
    const lanes = groupWaterfallLanes(extractWaterfallSteps(buildFixtureTimeline()));
    expect(lanes.map((l) => l.group)).toEqual(['task_1', 'task_1_agents']);
    expect(lanes[0].steps).toHaveLength(3); // tools
    expect(lanes[1].steps).toHaveLength(1); // agent
  });

  it('null parallelGroup 归一为 (serial)', () => {
    const lanes = groupWaterfallLanes(
      extractWaterfallSteps([
        mk({ eventType: 'step_start', stepId: 'x', parallelGroup: null }),
        mk({ eventType: 'step_done', stepId: 'x', durationMs: 100 }),
      ]),
    );
    expect(lanes[0].group).toBe('(serial)');
  });
});

describe('buildWaterfallLayout', () => {
  it('bar 宽度反映真实耗时：width(s3) > width(s6) > width(s1)', () => {
    const layout = buildWaterfallLayout(buildFixtureTimeline());
    const s1 = layout.bars.get('s1')!;
    const s3 = layout.bars.get('s3')!;
    const s6 = layout.bars.get('s6')!;

    expect(layout.hasData).toBe(true);
    expect(s3.widthPercent).toBeGreaterThan(s6.widthPercent);
    expect(s6.widthPercent).toBeGreaterThan(s1.widthPercent);
  });

  it('同组并行 step 起点对齐（left ≈ 0），后续泳道起点右移', () => {
    const layout = buildWaterfallLayout(buildFixtureTimeline());
    const s1 = layout.bars.get('s1')!;
    const s3 = layout.bars.get('s3')!;
    const s6 = layout.bars.get('s6')!;
    const s8 = layout.bars.get('s8')!;

    // task_1 三个并行 tool 起点一致（同秒 start → origin）
    expect(s1.leftPercent).toBeCloseTo(0, 5);
    expect(s3.leftPercent).toBeCloseTo(0, 5);
    expect(s6.leftPercent).toBeCloseTo(0, 5);
    // agent 晚 3s 启动，左偏移 > 0
    expect(s8.leftPercent).toBeGreaterThan(0);
  });

  it('空 timeline 返回 hasData=false', () => {
    const layout = buildWaterfallLayout([]);
    expect(layout.hasData).toBe(false);
    expect(layout.lanes).toHaveLength(0);
    expect(layout.bars.size).toBe(0);
  });
});
