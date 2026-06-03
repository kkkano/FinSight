import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { QualityBadge } from './QualityBadge';
import type { ReportQuality } from '../../types/index';

const renderText = (node: React.ReactElement) =>
  renderToStaticMarkup(node).replace(/\s+/g, ' ');

describe('QualityBadge', () => {
  it('renders nothing when quality is missing', () => {
    expect(renderToStaticMarkup(<QualityBadge quality={null} />)).toBe('');
    expect(renderToStaticMarkup(<QualityBadge quality={undefined} />)).toBe('');
  });

  it('renders nothing when state is unrecognized', () => {
    const quality = { state: 'unknown', reasons: [] } as unknown as ReportQuality;
    expect(renderToStaticMarkup(<QualityBadge quality={quality} />)).toBe('');
  });

  it('renders green pass badge', () => {
    const quality: ReportQuality = { state: 'pass', reasons: [] };
    const text = renderText(<QualityBadge quality={quality} />);
    expect(text).toContain('质量验证通过');
    expect(text).toContain('emerald');
  });

  it('renders amber warn badge with reason count', () => {
    const quality: ReportQuality = {
      state: 'warn',
      reasons: [
        { code: 'low_grounding', severity: 'warn', metric: 'grounding_rate', message: '接地率偏低' },
        { code: 'low_confidence', severity: 'warn', metric: 'confidence', message: '置信度不足' },
      ],
    };
    const text = renderText(<QualityBadge quality={quality} />);
    expect(text).toContain('质量提示 2 项');
    expect(text).toContain('amber');
  });

  it('renders red block badge', () => {
    const quality: ReportQuality = {
      state: 'block',
      reasons: [
        { code: 'hard_block', severity: 'block', metric: 'grounding_rate', message: '接地率过低被拦截' },
      ],
    };
    const text = renderText(<QualityBadge quality={quality} />);
    expect(text).toContain('质量门控拦截');
    expect(text).toContain('rose');
  });

  it('treats soft_blocked as block (red)', () => {
    const quality = {
      state: 'soft_blocked',
      reasons: [],
    } as unknown as ReportQuality;
    const text = renderText(<QualityBadge quality={quality} />);
    expect(text).toContain('质量门控拦截');
    expect(text).toContain('rose');
  });

  it('renders warn badge as a clickable button for expansion', () => {
    const quality: ReportQuality = {
      state: 'warn',
      reasons: [
        { code: 'low_grounding', severity: 'warn', metric: 'grounding_rate', message: '接地率偏低' },
      ],
    };
    const text = renderText(<QualityBadge quality={quality} />);
    // 可展开时 aria-expanded 应存在（初始折叠 = false）
    expect(text).toContain('aria-expanded="false"');
  });
});
