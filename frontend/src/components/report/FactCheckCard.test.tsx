import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { FactCheckCard } from './FactCheckCard';
import type { FactCheck } from './FactCheckCard';

const renderText = (node: React.ReactElement) =>
  renderToStaticMarkup(node).replace(/\s+/g, ' ');

describe('FactCheckCard', () => {
  it('returns nothing when factCheck is missing', () => {
    expect(renderToStaticMarkup(<FactCheckCard factCheck={null} />)).toBe('');
    expect(renderToStaticMarkup(<FactCheckCard factCheck={undefined} />)).toBe('');
  });

  it('renders the all-passed state when redaction_count is 0', () => {
    const factCheck: FactCheck = {
      verifier_claims: [],
      redaction_count: 0,
      verified_at: '2026-06-03T08:00:00Z',
      enabled: true,
      checked: true,
    };

    const text = renderText(<FactCheckCard factCheck={factCheck} />);

    expect(text).toContain('事实核查');
    expect(text).toContain('全部通过');
    expect(text).toContain('未发现不可信内容');
  });

  it('renders the warning state with claim list when redaction_count is greater than 0', () => {
    const factCheck: FactCheck = {
      verifier_claims: [
        { claim: 'Gemini 2.0 将于 2026Q2 发布', reason: '证据池中未找到对应记录' },
        { claim: '营收同比增长 50%', reason: '证据显示仅为 11%' },
      ],
      redaction_count: 2,
      verified_at: '2026-06-03T08:00:00Z',
      enabled: true,
      checked: true,
    };

    const text = renderText(<FactCheckCard factCheck={factCheck} />);

    expect(text).toContain('事实核查');
    expect(text).toContain('2 条声明未通过验证');
    expect(text).toContain('Gemini 2.0 将于 2026Q2 发布');
    expect(text).toContain('证据池中未找到对应记录');
    expect(text).toContain('营收同比增长 50%');
  });

  it('collapses claims beyond the first three into an expandable section', () => {
    const claims = Array.from({ length: 5 }, (_, i) => ({
      claim: `断言编号 ${i}`,
      reason: `原因 ${i}`,
    }));
    const factCheck: FactCheck = {
      verifier_claims: claims,
      redaction_count: 5,
    };

    const text = renderText(<FactCheckCard factCheck={factCheck} />);

    // 折叠区提示文案：默认展开 3 条，其余 2 条收起
    expect(text).toContain('展开其余 2 条');
    // 收起的条目仍在服务端渲染的 DOM 中
    expect(text).toContain('断言编号 4');
  });

  it('falls back to default reason when reason is empty', () => {
    const factCheck: FactCheck = {
      verifier_claims: [{ claim: '某条断言', reason: '' }],
      redaction_count: 1,
    };

    const text = renderText(<FactCheckCard factCheck={factCheck} />);

    expect(text).toContain('某条断言');
    expect(text).toContain('1 条声明未通过验证');
  });
});
