import { describe, expect, it } from 'vitest';

import { parseAgentMentions } from './useAgentMention';

describe('parseAgentMentions（@agent 手动选解析）', () => {
  it('解析单个 @agent', () => {
    expect(parseAgentMentions('分析 AAPL @price_agent')).toEqual(['price_agent']);
  });

  it('无 @ 时返回空 → 走自动模式', () => {
    expect(parseAgentMentions('分析 AAPL 走势')).toEqual([]);
  });

  it('解析多个 @agent 并按出现顺序去重', () => {
    expect(
      parseAgentMentions('@price_agent @news_agent 再看 @price_agent'),
    ).toEqual(['price_agent', 'news_agent']);
  });

  it('行首 @agent 也能识别', () => {
    expect(parseAgentMentions('@technical_agent RSI 怎么样')).toEqual([
      'technical_agent',
    ]);
  });

  it('email 内的 @ 不误触发（@ 前须为空白或行首）', () => {
    expect(parseAgentMentions('user@example 你好')).toEqual([]);
  });
});
