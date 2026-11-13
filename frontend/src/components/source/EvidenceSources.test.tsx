import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { EvidenceSources } from "./EvidenceSources";
import { evidenceSourceGroup } from "./EvidenceSources.utils";

describe('grouped answer sources', () => {
  it('keeps six or fewer sources flat and preserves provider names, evidence numbers and titles', () => {
    const sources = [
      { source_id: 'S1', title: '公司更新', source: 'Yahoo', url: 'https://finance.yahoo.com/news/one' },
      { source_id: 'S2', title: '行业跟踪', source: 'ChartMill', url: 'https://chartmill.com/news/two' },
      { source_id: 'S3', title: '供应链变化', source: 'yfinance', url: 'https://uk.finance.yahoo.com/news/three' },
    ];
    const html = renderToStaticMarkup(<EvidenceSources sources={sources} />);
    expect(html).not.toContain('data-testid="source-group"');
    expect(html).toContain('2 类 · 3 项');
    expect(html).toContain('Yahoo Finance');
    expect(html).toContain('供应链变化');
    expect(html).toContain('>3</span>');
    expect(html).not.toContain('<details open');
  });

  it('groups larger source lists while keeping all seven reference numbers', () => {
    const sources = Array.from({ length: 7 }, (_, index) => ({ source_id: `S${index + 1}`, title: `资料${index + 1}`,
      source: index < 4 ? 'Yahoo' : 'reuters', url: `https://example.com/${index + 1}` }));
    const html = renderToStaticMarkup(<EvidenceSources sources={sources} />);
    expect(html.match(/data-testid="source-group"/g)).toHaveLength(2);
    expect(html).toContain('>7</span>');
    expect(html).toContain('2 类 · 7 项');
  });

  it('uses the media host when a news source has no provider label', () => {
    expect(evidenceSourceGroup({ title: '新闻', url: 'https://uk.finance.yahoo.com/news/example' })).toBe('Yahoo Finance');
  });
});
