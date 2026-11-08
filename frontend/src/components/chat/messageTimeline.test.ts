import { describe, expect, it } from 'vitest';
import { buildMessageTimeline } from './messageTimeline';

describe('message event sequence', () => {
  it('keeps text before and after tool work in its original event positions', () => {
    const timeline = buildMessageTimeline([
      { id: 'intro', kind: 'text', content: '先说明分析范围。', content_phase: 'progress', revision: 0, seq: 1 },
      { id: 'thought', kind: 'reasoning', reasoning_kind: 'provider_raw', content: '核查原始资料。', revision: 0, seq: 2 },
      { id: 'answer', kind: 'text', content: '这是取证后的结论。', revision: 0, seq: 6 },
    ], [
      { stage: 'tool_start', timestamp: '', result: { name: 'get_stock_price', tool_call_id: 'quote', seq: 3 } },
      { stage: 'tool_end', timestamp: '', result: { name: 'get_stock_price', tool_call_id: 'quote', seq: 4 } },
      { stage: 'tool_end', timestamp: '', result: { name: 'search', tool_call_id: 'search', seq: 5 } },
    ], false);
    expect(timeline.map((item) => item.kind === 'block' ? item.block.id : 'tools')).toEqual(['intro', 'thought', 'tools', 'answer']);
    expect(timeline[2]).toMatchObject({ rows: [{ id: 'quote' }, { id: 'search' }] });
  });
});
