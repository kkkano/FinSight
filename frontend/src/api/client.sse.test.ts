import { afterEach, describe, expect, it, vi } from 'vitest';

import { apiClient, parseSSEStream, RATE_LIMIT_EVENT, rateLimitEvents, withStreamGuards } from './client';

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

function sseResponseWithHeaders(
  events: Array<Record<string, unknown>>,
  headers: Record<string, string>,
): Response {
  const response = sseResponse(events);
  return new Response(response.body, { headers });
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

describe('SSE read timeout (P1-2)', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it('reports a connection error when no data arrives within the read timeout', async () => {
    vi.useFakeTimers();
    // 一个永远不发数据的流，模拟连接挂死（网络断/Tunnel 超时）
    const stream = new ReadableStream({ start() { /* never enqueue */ } });
    const response = new Response(stream);
    const onError = vi.fn();
    const onDone = vi.fn();

    const promise = parseSSEStream(response, { onError, onDone }, { readTimeoutMs: 1000 });
    await vi.advanceTimersByTimeAsync(1100);
    await promise;

    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError.mock.calls[0][0]).toContain('连接中断');
    expect(onDone).not.toHaveBeenCalled();
  });

  it('does not time out while frames keep arriving (heartbeats reset the timer)', async () => {
    vi.useFakeTimers();
    const encoder = new TextEncoder();
    let pushCount = 0;
    let intervalId: ReturnType<typeof setInterval> | null = null;

    // 每 500ms 发一个心跳帧，发 5 个之后正常结束（总时长 2500ms > 单次超时 1000ms）
    const stream = new ReadableStream({
      start(controller) {
        intervalId = setInterval(() => {
          pushCount += 1;
          controller.enqueue(encoder.encode('data: {"type":"heartbeat"}\n\n'));
          if (pushCount >= 5) {
            if (intervalId) clearInterval(intervalId);
            controller.close();
          }
        }, 500);
      },
    });
    const response = new Response(stream);
    const onError = vi.fn();

    const promise = parseSSEStream(response, { onError }, { readTimeoutMs: 1000 });
    await vi.advanceTimersByTimeAsync(3000);
    await promise;

    expect(onError).not.toHaveBeenCalled();
  });

  it('does not report timeout error when stream was aborted', async () => {
    vi.useFakeTimers();
    const controller = new AbortController();
    const stream = new ReadableStream({ start() { /* never enqueue */ } });
    const response = new Response(stream);
    const onError = vi.fn();

    const promise = parseSSEStream(
      response,
      { onError },
      { readTimeoutMs: 1000, signal: controller.signal },
    );
    controller.abort();
    await vi.advanceTimersByTimeAsync(1100);
    await promise;

    expect(onError).not.toHaveBeenCalled();
  });
});

describe('withStreamGuards', () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('deduplicates terminal callbacks', () => {
    const onDone = vi.fn();
    const onError = vi.fn();
    const guarded = withStreamGuards({ onDone, onError });

    guarded.onDone?.();
    guarded.onDone?.();
    guarded.finish();

    expect(onDone).toHaveBeenCalledTimes(1);
    expect(onError).not.toHaveBeenCalled();
  });

  it('never turns an incomplete stream into synthetic done', () => {
    const onDone = vi.fn();
    const onError = vi.fn();
    const guarded = withStreamGuards({ onDone, onError });

    guarded.onToken?.('partial');
    guarded.finish();

    expect(onDone).not.toHaveBeenCalled();
    expect(onError).toHaveBeenCalledWith(expect.stringContaining('内容可能不完整'));
  });
});

describe('chat SSE auto resume', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('replays only events after the last sequence and completes once', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(sseResponseWithHeaders(
        [{ type: 'token', content: 'A', run_id: 'run-1', seq: 1 }],
        { 'X-Run-Id': 'run-1' },
      ))
      .mockResolvedValueOnce(sseResponse([
        { type: 'token', content: 'B', run_id: 'run-1', seq: 2 },
        { type: 'done', response: 'AB', run_id: 'run-1', seq: 3 },
      ]));
    vi.stubGlobal('fetch', fetchMock);
    const tokens: string[] = [];
    const onDone = vi.fn();
    const onError = vi.fn();
    const connectionStates: string[] = [];

    await apiClient.sendMessageStream(
      { query: 'AAPL 分析' },
      { onToken: (token) => tokens.push(String(token)), onDone, onError },
      {
        reconnectDelaysMs: [0, 0],
        onConnectionState: (state) => connectionStates.push(state),
      },
    );

    expect(tokens).toEqual(['A', 'B']);
    expect(onDone).toHaveBeenCalledTimes(1);
    expect(onError).not.toHaveBeenCalled();
    expect(fetchMock.mock.calls[1][0]).toContain('/api/chat/stream/run-1?after_seq=1');
    expect(connectionStates).toEqual(['reconnecting', 'connected']);
  });

  it('tries resume at most twice before reporting honest connection loss', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(sseResponseWithHeaders(
        [{ type: 'token', content: 'partial', run_id: 'run-2', seq: 1 }],
        { 'X-Run-Id': 'run-2' },
      ))
      .mockRejectedValueOnce(new Error('offline-1'))
      .mockRejectedValueOnce(new Error('offline-2'));
    vi.stubGlobal('fetch', fetchMock);
    const onDone = vi.fn();
    const onError = vi.fn();
    const connectionStates: string[] = [];

    await apiClient.sendMessageStream(
      { query: 'AAPL 分析' },
      { onDone, onError },
      {
        reconnectDelaysMs: [0, 0],
        onConnectionState: (state) => connectionStates.push(state),
      },
    );

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(onDone).not.toHaveBeenCalled();
    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError.mock.calls[0][0]).toContain('内容可能不完整');
    expect(connectionStates).toEqual(['reconnecting', 'reconnecting', 'lost']);
  });
});

describe('429 rate limit event (P1-8)', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('dispatches a rate-limit event when stream endpoint returns 429', async () => {
    const listener = vi.fn();
    rateLimitEvents.addEventListener(RATE_LIMIT_EVENT, listener);

    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response('rate limited', {
          status: 429,
          headers: { 'Retry-After': '30' },
        }),
      ),
    );

    await expect(
      apiClient.sendMessageStream({ query: 'AAPL 分析' }, { onToken: vi.fn() }),
    ).rejects.toThrow();

    expect(listener).toHaveBeenCalledTimes(1);
    const detail = (listener.mock.calls[0][0] as CustomEvent).detail;
    expect(detail.retryAfterSeconds).toBe(30);

    rateLimitEvents.removeEventListener(RATE_LIMIT_EVENT, listener);
  });

  it('dispatches a rate-limit event with null retry-after when header missing', async () => {
    const listener = vi.fn();
    rateLimitEvents.addEventListener(RATE_LIMIT_EVENT, listener);

    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response('rate limited', { status: 429 })),
    );

    await expect(
      apiClient.executeAgent(
        { query: 'AAPL', session_id: 'public:user:thread' },
        {},
      ),
    ).rejects.toThrow();

    expect(listener).toHaveBeenCalledTimes(1);
    const detail = (listener.mock.calls[0][0] as CustomEvent).detail;
    expect(detail.retryAfterSeconds).toBeNull();

    rateLimitEvents.removeEventListener(RATE_LIMIT_EVENT, listener);
  });
});
