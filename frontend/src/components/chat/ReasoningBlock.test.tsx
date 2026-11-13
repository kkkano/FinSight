import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { ReasoningBlock } from './ReasoningBlock';
import type { ResearchBlock } from '../../types/runtime';

const block: Extract<ResearchBlock, { kind: 'reasoning' }> = {
  id: 'public-summary', kind: 'reasoning', content: '公开摘要内容', revision: 0, seq: 1,
  reasoning_kind: 'public_summary', duration_ms: 1400, truncated: true,
};

describe('reasoning presentation', () => {
  it('keeps a completed summary collapsed with the original label and duration', () => {
    const html = renderToStaticMarkup(<ReasoningBlock block={block} />);
    expect(html).toContain('aria-expanded="false"');
    expect(html).toContain('思考过程');
    expect(html).toContain('1.4秒');
    expect(html).not.toContain('data-testid="reasoning-content"');
  });

  it('opens the live summary and retains its truncation notice without a token live region', () => {
    const html = renderToStaticMarkup(<ReasoningBlock block={block} live />);
    expect(html).toContain('aria-expanded="true"');
    expect(html).toContain('data-testid="reasoning-content"');
    expect(html).toContain('思考内容较长，超出保存上限的部分没有保留。');
    expect(html).not.toContain('aria-live');
  });
});
