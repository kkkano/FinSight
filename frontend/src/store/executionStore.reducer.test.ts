import { describe, expect, it } from 'vitest';

import { pipelineReducer } from './executionStore';
import type {
  AgentRunInfo,
  ExecutionRun,
  PipelineStage,
  PipelineStageState,
  TimelineEvent,
} from '../types/execution';

function buildPipelineStages(): Record<PipelineStage, PipelineStageState> {
  return {
    planning: { stage: 'planning', status: 'pending' },
    executing: { stage: 'executing', status: 'pending' },
    synthesizing: { stage: 'synthesizing', status: 'pending' },
    rendering: { stage: 'rendering', status: 'pending' },
    done: { stage: 'done', status: 'pending' },
  };
}

function buildRun(overrides: Partial<ExecutionRun> = {}): ExecutionRun {
  return {
    runId: 'run-test-1',
    query: 'AAPL outlook',
    tickers: ['AAPL'],
    source: 'unit_test',
    outputMode: 'brief',
    analysisDepth: 'report',
    status: 'running',
    agentStatuses: {},
    pipelineStages: buildPipelineStages(),
    pipelineCurrentStage: null,
    selectedAgents: [],
    skippedAgents: [],
    planSteps: [],
    hasParallelPlan: false,
    reasoningBrief: undefined,
    decisionNotes: [],
    etaSeconds: null,
    progress: 0,
    currentStep: '准备执行',
    timeline: [],
    report: null,
    streamedContent: '',
    fallbackReasons: [],
    error: null,
    startedAt: '2026-02-19T00:00:00.000Z',
    completedAt: null,
    abortController: null,
    bridgedToChat: false,
    interruptData: null,
    ...overrides,
  };
}

function buildTimelineEvent(eventType: string): TimelineEvent {
  return {
    id: `evt-${eventType}`,
    timestamp: '2026-02-19T00:00:01.000Z',
    eventType,
    stage: eventType,
    runId: 'run-test-1',
  };
}

describe('pipelineReducer', () => {
  it('consumes plan_ready and initializes plan metadata', () => {
    const run = buildRun();
    const step = {
      eventType: 'plan_ready',
      message: 'Plan generated',
      timestamp: '2026-02-19T00:00:01.000Z',
      result: {
        type: 'plan_ready',
        plan_steps: [
          { id: 's1', kind: 'agent', name: 'news_agent', optional: false },
          { id: 's2', kind: 'agent', name: 'technical_agent', optional: false, parallel_group: 'p1' },
        ],
        selected_agents: ['news_agent', 'technical_agent'],
        skipped_agents: ['macro_agent'],
        has_parallel: true,
        reasoning_brief: 'Selected agents based on user request.',
      },
    };

    const patch = pipelineReducer(run, step, [buildTimelineEvent('plan_ready')]);
    expect(patch.planSteps).toHaveLength(2);
    expect(patch.selectedAgents).toEqual(['news_agent', 'technical_agent']);
    expect(patch.skippedAgents).toEqual(['macro_agent']);
    expect(patch.hasParallelPlan).toBe(true);
    expect(patch.reasoningBrief).toContain('Selected agents');
    expect((patch.progress ?? 0) >= 8).toBe(true);
  });

  it('advances pipeline stage on pipeline_stage event', () => {
    const run = buildRun({ progress: 10 });
    const step = {
      eventType: 'pipeline_stage',
      stage: 'pipeline_stage',
      message: 'Executor started',
      timestamp: '2026-02-19T00:00:02.000Z',
      result: {
        type: 'pipeline_stage',
        stage: 'executing',
        status: 'start',
        message: 'Executor started',
      },
    };

    const patch = pipelineReducer(run, step, [buildTimelineEvent('pipeline_stage')]);
    expect(patch.pipelineCurrentStage).toBe('executing');
    expect(patch.pipelineStages?.executing.status).toBe('running');
    expect((patch.progress ?? 0) >= 35).toBe(true);
  });

  it('maps agent_done metrics into AgentRunInfo', () => {
    const run = buildRun({
      progress: 30,
      agentStatuses: {
        news_agent: {
          name: 'news_agent',
          status: 'running',
        } satisfies AgentRunInfo,
      },
    });
    const step = {
      eventType: 'agent_done',
      timestamp: '2026-02-19T00:00:03.000Z',
      result: {
        type: 'agent_done',
        agent: 'news_agent',
        confidence: 0.91,
        evidence_count: 7,
        data_sources: ['reuters', 'sec'],
        duration_ms: 1234,
      },
    };

    const patch = pipelineReducer(run, step, [buildTimelineEvent('agent_done')]);
    const mapped = patch.agentStatuses?.news_agent;
    expect(mapped?.status).toBe('done');
    expect(mapped?.confidence).toBe(0.91);
    expect(mapped?.evidenceCount).toBe(7);
    expect(mapped?.dataSources).toEqual(['reuters', 'sec']);
    expect(mapped?.durationMs).toBe(1234);
  });

  it('keeps graceful fallback for unknown event with message', () => {
    const run = buildRun({ progress: 42 });
    const step = {
      eventType: 'custom_event',
      stage: 'custom_event',
      message: 'custom status message',
      timestamp: '2026-02-19T00:00:04.000Z',
      result: {},
    };

    const patch = pipelineReducer(run, step, [buildTimelineEvent('custom_event')]);
    expect(patch.currentStep).toBe('custom status message');
    expect(patch.progress === undefined || patch.progress >= 42).toBe(true);
  });
});
