import { describe, expect, it } from 'vitest';
import { bindResearchCitations, citationId } from './researchCitations';

describe('research citation links', () => {
  it('binds only evidence actually attached to the message', () => {
    const sources = [{ source_id: 'Sabc123', title: '公司公告', url: 'https://example.com' }];
    expect(bindResearchCitations('增长来源[Sabc123]；未知[Sffff]。', sources)).toBe('增长来源[1](#research-source-Sabc123)；未知[Sffff]。');
    expect(citationId(sources[0], 0)).toBe('Sabc123');
  });
});
