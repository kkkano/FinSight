import { describe, expect, it } from 'vitest';

import { parseSSEStream } from './client';

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
});
