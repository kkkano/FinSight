import { describe, expect, it } from 'vitest';

import {
  buildMonitorCommentStreamPath,
  classifyMonitorStreamResponse,
} from './useMonitorCommentFeed';

describe('useMonitorCommentFeed response policy', () => {
  it('treats 503 as terminal unavailable while retaining retries for transient failures', () => {
    expect(classifyMonitorStreamResponse({ status: 503, ok: false, body: null }))
      .toBe('terminal_unavailable');
    expect(classifyMonitorStreamResponse({ status: 500, ok: false, body: null }))
      .toBe('retryable_error');
    expect(classifyMonitorStreamResponse({ status: 200, ok: true, body: {} as ReadableStream }))
      .toBe('stream');
  });

  it('binds every stream to the current normalized symbol', () => {
    expect(buildMonitorCommentStreamPath('session:1', ' aapl '))
      .toBe('/api/monitor/comments/stream?session_id=session%3A1&symbol=AAPL');
    expect(buildMonitorCommentStreamPath('session:1', 'msft', 'event-1'))
      .toContain('symbol=MSFT&last_event_id=event-1');
  });
});
