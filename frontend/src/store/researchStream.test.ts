import { describe, expect, it } from 'vitest';
import { applyResearchEvent, emptyResearchStream, normalizeRuntimeEvent, publicResearchBlocks, researchFailureMessage, researchQualityMessage, researchText } from './researchStream';
import type { RuntimeEvent } from '../types/runtime';

const event = (seq: number, delta: string, extras: Partial<RuntimeEvent> = {}): RuntimeEvent => ({
  type: 'content.delta', run_id: 'run-a', session_id: 'session-a', stream_epoch: 'epoch-a', seq,
  payload: { block_id: 'answer', delta }, ...extras,
});

describe('research stream identity and recovery', () => {
  it('applies a repeated delta once and rejects a foreign run', () => {
    const first = applyResearchEvent(emptyResearchStream('run-a'), event(1, '财报'));
    expect(applyResearchEvent(first, event(1, '财报'))).toBe(first);
    expect(applyResearchEvent(first, event(2, 'foreign', { run_id: 'run-b' }))).toBe(first);
    expect(researchText(applyResearchEvent(first, event(3, '增长')).blocks)).toBe('财报增长');
  });
  it('accepts a committed snapshot with a new epoch even when its sequence is lower', () => {
    const first = applyResearchEvent(emptyResearchStream('run-a'), event(90, 'unsaved'));
    const recovered = applyResearchEvent(first, { type: 'snapshot.reset', run_id: 'run-a', stream_epoch: 'epoch-b', seq: 3,
      payload: { committed_seq: 3, blocks: [{ id: 'answer', kind: 'text', content: '已保存', revision: 1 }] } });
    expect(researchText(recovered.blocks)).toBe('已保存');
    expect(applyResearchEvent(recovered, event(91, 'late'))).toBe(recovered);
    expect(researchText(applyResearchEvent(recovered, event(4, '正文', { stream_epoch: 'epoch-b' })).blocks)).toBe('已保存正文');
  });
  it('updates a content revision in place rather than appending a second answer', () => {
    const first = applyResearchEvent(emptyResearchStream('run-a'), event(1, '旧口径'));
    const revised = applyResearchEvent(first, event(2, '', { type: 'content.revised', payload: { block_id: 'answer', content: '已校正', revision: 2 } }));
    expect(revised.blocks).toHaveLength(1);
    expect(researchText(revised.blocks)).toBe('已校正');
  });
  it('keeps finished progress in sequence without copying it into the answer', () => {
    let state = applyResearchEvent(emptyResearchStream('run-a'), event(1, '我先查看现金流。', { payload: { block_id: 'intro', delta: '我先查看现金流。' } }));
    state = applyResearchEvent(state, event(2, '', { type: 'content.block_finished', payload: { block_id: 'intro', content_phase: 'progress' } }));
    expect(state.blocks[0]).toMatchObject({ content: '我先查看现金流。', content_phase: 'progress', seq: 1 });
    expect(researchText(state.blocks)).toBe('');
    state = applyResearchEvent(state, event(3, '正式结论。', { payload: { block_id: 'final', delta: '正式结论。' } }));
    state = applyResearchEvent(state, event(4, '', { type: 'content.block_finished', content_phase: 'answer', payload: { block_id: 'final' } }));
    expect(researchText(state.blocks)).toBe('正式结论。');
    expect(researchText(publicResearchBlocks(state.blocks))).toBe('正式结论。');
    expect(state.blocks[1]).toMatchObject({ content: '正式结论。', content_phase: 'answer', seq: 3 });
  });
  it('removes an invalid candidate without inventing a withdrawal placeholder', () => {
    const before = applyResearchEvent(emptyResearchStream('run-a'), event(1, '待修正的说法。'));
    const after = applyResearchEvent(before, event(2, '', { type: 'content.revised',
      payload: { block_id: 'answer', content: '', revision: 1, content_phase: 'progress' } }));
    expect(after.blocks[0]).toMatchObject({ content: '', content_phase: 'progress', revision: 1, seq: 1 });
    expect(researchText(after.blocks)).toBe('');
    expect(before.blocks[0]).toMatchObject({ content: '待修正的说法。' });
  });
  it('saves supplied reasoning with its owning run and keeps it out of answer text', () => {
    const summary = (seq: number, delta: string) => event(seq, '', { type: 'reasoning.delta', payload: { kind: 'public_summary', delta } });
    let state = applyResearchEvent(emptyResearchStream('run-a'), summary(1, '核查'));
    state = applyResearchEvent(state, summary(2, '来源'));
    expect(state.blocks[0]).toMatchObject({ kind: 'reasoning', content: '核查来源' });
    const raw = event(3, '', { type: 'reasoning.delta', payload: { kind: 'provider_raw', delta: 'raw-content' } });
    state = applyResearchEvent(state, raw);
    expect(state.blocks[1]).toMatchObject({ kind: 'reasoning', reasoning_kind: 'provider_raw', content: 'raw-content', seq: 3 });
    expect(researchText(state.blocks)).toBe('');
    expect(applyResearchEvent(state, { ...raw, run_id: 'different-owner-run' })).toBe(state);
    expect(publicResearchBlocks(state.blocks)[1]).toMatchObject({ content: 'raw-content' });
  });
  it('caps the entire run including child reasoning at 20000 characters and marks truncation', () => {
    const first = applyResearchEvent(emptyResearchStream('run-a'), event(1, '', { type: 'reasoning.delta',
      payload: { kind: 'provider_raw', block_id: 'root-reasoning', delta: 'a'.repeat(19000) } }));
    const second = applyResearchEvent(first, event(2, '', { type: 'reasoning.delta',
      payload: { kind: 'provider_raw', block_id: 'child-reasoning', delta: 'b'.repeat(2000), agent_id: 'child' } }));
    expect(second.blocks[1]).toMatchObject({ content: 'b'.repeat(1000), truncated: true, agent_id: 'child' });
    const restored = publicResearchBlocks([{ id: 'root', kind: 'reasoning', reasoning_kind: 'provider_raw', content: 'a'.repeat(15000), revision: 0 },
      { id: 'child', kind: 'reasoning', reasoning_kind: 'provider_raw', content: 'b'.repeat(15000), revision: 0 }]);
    expect(restored[1]).toMatchObject({ content: 'b'.repeat(5000), truncated: true });
  });
  it('normalizes one backwards-compatible token into one typed delta', () => {
    expect(normalizeRuntimeEvent({ schema_version: 2, type: 'token', runtime_type: 'content.delta', content: '一次', block_id: 'b', seq: 1 }))
      .toMatchObject({ type: 'content.delta', payload: { delta: '一次', block_id: 'b' } });
    expect(normalizeRuntimeEvent({ type: 'token', content: 'legacy' })).toBeNull();
  });

  it('preserves a specific terminal message and explains known codes in old generic errors', () => {
    expect(researchFailureMessage({ error_code: 'model_timeout', message: '等待模型生成结论超过本轮时限。' }))
      .toBe('等待模型生成结论超过本轮时限。');
    expect(researchFailureMessage({ error_code: 'model_timeout', message: '本轮研究未完成，已保留可用内容。' }))
      .toBe('模型响应超时，研究已中断。');
    expect(researchFailureMessage({ reason: '盈利预期服务未返回数据。', error_code: 'model_timeout', recovery_action: '稍后重试。' }))
      .toBe('盈利预期服务未返回数据。 稍后重试。');
  });

  it('keeps report evidence failures in the completed research explanation', () => {
    expect(researchQualityMessage({ quality: { reasons: [{ message: '来源不足。' }] },
      report_quality: { reasons: [{ message: '来源不足。' }, { message: '部分数值未通过核验。' }] } }))
      .toBe('来源不足。 部分数值未通过核验。');
  });

});

