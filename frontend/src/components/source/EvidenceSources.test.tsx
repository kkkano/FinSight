import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { EvidenceSources, evidenceSourceGroup } from './EvidenceSources';

describe('grouped answer sources', () => {
  it('groups Yahoo variants together and preserves original evidence numbers and titles', () => {
    const sources = [
      { source_id: 'S1', title: '公司更新', source: 'Yahoo', url: 'https://finance.yahoo.com/news/one' },
      { source_id: 'S2', title: '行业跟踪', source: 'ChartMill', url: 'https://chartmill.com/news/two' },
      { source_id: 'S3', title: '供应链变化', source: 'yfinance', url: 'https://uk.finance.yahoo.com/news/three' },
    ];
    const html = renderToStaticMarkup(<EvidenceSources sources={sources} />);
    expect(html.match(/data-testid="source-group"/g)).toHaveLength(2);
    expect(html).toContain('2 类 · 3 项');
    expect(html).toContain('Yahoo Finance');
    expect(html).toContain('供应链变化');
    expect(html).toContain('>3</span>');
    expect(html).not.toContain('<details open');
  });

  it('uses the media host when a news source has no provider label', () => {
    expect(evidenceSourceGroup({ title: '新闻', url: 'https://uk.finance.yahoo.com/news/example' })).toBe('Yahoo Finance');
  });
});
