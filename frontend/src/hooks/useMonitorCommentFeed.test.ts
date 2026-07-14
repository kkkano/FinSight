import { describe, expect, it } from 'vitest';

import { classifyMonitorStreamResponse } from './useMonitorCommentFeed';

describe('useMonitorCommentFeed response policy', () => {
  it('treats 503 as terminal unavailable while retaining retries for transient failures', () => {
    expect(classifyMonitorStreamResponse({ status: 503, ok: false, body: null }))
      .toBe('terminal_unavailable');
    expect(classifyMonitorStreamResponse({ status: 500, ok: false, body: null }))
      .toBe('retryable_error');
    expect(classifyMonitorStreamResponse({ status: 200, ok: true, body: {} as ReadableStream }))
      .toBe('stream');
  });
});
