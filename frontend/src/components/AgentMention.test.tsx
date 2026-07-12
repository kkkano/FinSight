import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import type { AgentItem } from '../hooks/useAgentMention';
import { AgentMention } from './AgentMention';

const agents: AgentItem[] = [{
  name: 'technical_agent',
  display_name: '技术面分析师',
  short_zh: '技术面',
  description: '技术分析',
  glyph: 'T',
  color_token: 't-predict',
  mandate: '趋势、动量、关键价位与量价结构',
  insert_text: '@technical_agent ',
  track_record: { sample_state: 'sufficient', hit_rate: 0.7, sample_count: 20 },
}, {
  name: 'macro_agent',
  display_name: '宏观分析师',
  short_zh: '宏观',
  description: '宏观分析',
  glyph: 'M',
  color_token: 't-info',
  mandate: '利率、通胀与政策环境',
  insert_text: '@macro_agent ',
  track_record: { sample_state: 'insufficient', hit_rate: null, sample_count: 2 },
}];

describe('AgentMention', () => {
  it('展示 glyph、同源中文姓名、职责与充分样本命中率', () => {
    const html = renderToStaticMarkup(
      <AgentMention agents={agents} selectedIndex={0} onSelect={() => {}} />,
    );
    expect(html).toContain('T');
    expect(html).toContain('技术面分析师');
    expect(html).toContain('趋势、动量、关键价位与量价结构');
    expect(html).toContain('命中率 70%');
    expect(html).toContain('宏观分析师');
    expect(html).not.toContain('命中率 0%');
  });
});
