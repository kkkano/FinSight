import { describe, expect, it, vi } from 'vitest';
import { parseSSEStream } from './sse';

const response = (events: unknown[]) => new Response(events.map((event) => 'data: ' + JSON.stringify(event) + '\n\n').join(''));
describe('runtime SSE compatibility', () => {
  it('dispatches a v2-compatible token once to the runtime consumer', async () => {
    const onToken = vi.fn(); const onRuntimeEvent = vi.fn(); const onDone = vi.fn();
    await parseSSEStream(response([
      { schema_version: 2, type: 'token', content: '正文', seq: 1 },
      { type: 'done', response: '正文' },
    ]), { onToken, onRuntimeEvent, onDone }, { readTimeoutMs: 0 });
    expect(onRuntimeEvent).toHaveBeenCalledTimes(1);
    expect(onRuntimeEvent.mock.calls[0][0].payload.delta).toBe('正文');
    expect(onToken).not.toHaveBeenCalled();
    expect(onDone).toHaveBeenCalledTimes(1);
  });
  it('continues to supply tokens to legacy consumers', async () => {
    const onToken = vi.fn();
    await parseSSEStream(response([{ schema_version: 2, type: 'token', content: '正文' }, { type: 'done' }]), { onToken }, { readTimeoutMs: 0 });
    expect(onToken).toHaveBeenCalledExactlyOnceWith('正文');
  });
  it('does not forward provider reasoning to the raw developer log', async () => {
    const onRawEvent = vi.fn(); const onRuntimeEvent = vi.fn();
    await parseSSEStream(response([
      { schema_version: 2, type: 'reasoning.delta', payload: { kind: 'provider_raw', delta: 'private-field' } },
      { type: 'done' },
    ]), { onRawEvent, onRuntimeEvent }, { readTimeoutMs: 0 });
    expect(onRuntimeEvent).toHaveBeenCalledTimes(1);
    expect(JSON.stringify(onRawEvent.mock.calls)).not.toContain('private-field');
  });
  it('delivers a skill activation as visible research activity', async () => {
    const onThinking = vi.fn();
    await parseSSEStream(response([
      { schema_version: 2, type: 'skill.activated', payload: { skill_id: 'growth-quality', title: '成长质量', summary: '已应用成长质量研究方法。' } },
      { type: 'done' },
    ]), { onThinking }, { readTimeoutMs: 0 });
    expect(onThinking).toHaveBeenCalledWith(expect.objectContaining({ eventType: 'trace',
      result: expect.objectContaining({ runtime_type: 'skill.activated', skill_id: 'growth-quality', visibility: 'user' }) }));
  });
});

