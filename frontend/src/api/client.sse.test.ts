import { afterEach, describe, expect, it, vi } from 'vitest';

import { apiClient, parseSSEStream } from './client';

function sseResponse(events: Array<Record<string, unknown>>): Response {
  const body = events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join('');
  const stream = new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(body));
      controller.close();
    },
  });
  return new Response(stream);
}

describe('parseSSEStream', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('normalizes user-visible trace events into thinking callbacks', async () => {
    const thinking: any[] = [];
    const rawEvents: any[] = [];

    await parseSSEStream(
      sseResponse([
        {
          type: 'trace',
          stage: 'understanding',
          title: '已理解请求',
          summary: 'GOOGL:price；阻塞项:1',
          tasks: [{ id: 'task_1', operation: 'price' }],
        },
      ]),
      {
        onThinking: (step) => thinking.push(step),
        onRawEvent: (event) => rawEvents.push(event),
      },
      { traceRawEnabled: true },
    );

    expect(thinking).toHaveLength(1);
    expect(thinking[0]).toMatchObject({
      stage: 'understanding',
      message: 'GOOGL:price；阻塞项:1',
      eventType: 'trace',
    });
    expect(thinking[0].result.tasks).toHaveLength(1);
    expect(rawEvents[0].eventType).toBe('trace');
  });

  it('surfaces cancelled trace and pipeline events as thinking callbacks', async () => {
    const thinking: any[] = [];

    await parseSSEStream(
      sseResponse([
        {
          type: 'trace',
          stage: 'cancelled',
          status: 'cancelled',
          summary: '已停止生成，保留已完成的结果。',
        },
        {
          type: 'pipeline_stage',
          stage: 'cancelled',
          status: 'cancelled',
          message: 'Generation cancelled by client',
        },
      ]),
      {
        onThinking: (step) => thinking.push(step),
      },
      { traceRawEnabled: true },
    );

    expect(thinking).toHaveLength(2);
    expect(thinking[0]).toMatchObject({
      stage: 'cancelled',
      message: '已停止生成，保留已完成的结果。',
      eventType: 'trace',
    });
    expect(thinking[1]).toMatchObject({
      stage: 'cancelled',
      message: 'Generation cancelled by client',
      eventType: 'pipeline_stage',
    });
  });

  it('does not report missing done when execute stream was aborted', async () => {
    const controller = new AbortController();
    controller.abort();
    const onError = vi.fn();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(sseResponse([{ type: 'token', content: 'partial' }])));

    await apiClient.executeAgent(
      { query: 'AAPL', session_id: 'public:user:thread' },
      { onError },
      { signal: controller.signal },
    );

    expect(onError).not.toHaveBeenCalled();
  });

  it('does not report missing done when resume stream was aborted', async () => {
    const controller = new AbortController();
    controller.abort();
    const onError = vi.fn();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(sseResponse([{ type: 'token', content: 'partial' }])));

    await apiClient.resumeExecution(
      { thread_id: 'public:user:thread', resume_value: 'continue' },
      { onError },
      { signal: controller.signal },
    );

    expect(onError).not.toHaveBeenCalled();
  });
});
