import { describe, expect, it } from 'vitest';
import { bindResearchCitations, citationId } from './researchCitations';

describe('research citation links', () => {
  it('binds integer or numeric-string source IDs by identity instead of guessing array positions', () => {
    const sources = [{source_id:7,title:'第一项'}, {source_id:'1',title:'第二项'}];
    expect(bindResearchCitations('来源[1]；来源[7]；未知[2]',sources))
      .toBe('来源[2](#research-source-1)；来源[1](#research-source-7)；未知[2]');
    expect(bindResearchCitations('未知[1]', [{source_id:'Sabc',title:'旧来源'}])).toBe('未知[1]');
    expect(citationId({source_id:7},0)).toBe('7');
  });
  it('leaves linked citations, URLs, inline code and fenced code unchanged', () => {
    const content='[1](#research-source-1) [1](https://example.com/source) https://example.com/[1] `[1]`\n```text\n[1]\n```';
    expect(bindResearchCitations(content,[{source_id:1}])).toBe(content);
  });
  it('binds only evidence actually attached to the message', () => {
    const sources = [{ source_id: 'Sabc123', title: '公司公告', url: 'https://example.com' }];
    expect(bindResearchCitations('增长来源[Sabc123]；未知[Sffff]。', sources)).toBe('增长来源[1](#research-source-Sabc123)；未知[Sffff]。');
    expect(citationId(sources[0], 0)).toBe('Sabc123');
  });

  it('hides legacy data identifiers while preserving the linked source and financial facts', () => {
    const sources = [{ source_id: 'Sabc123', title: '公司公告' }];
    expect(bindResearchCitations('AAPL营收100亿美元，同比增长17.9%。[数据集 1fcdf70c3d755a3fd3，来源 Sabc123]\n根据 dataset_abcd1234。', sources))
      .toBe('AAPL营收100亿美元，同比增长17.9%。[1](#research-source-Sabc123)\n根据 研究数据。');
  });

  it('leaves source URLs and code fences unchanged', () => {
    const content = '[原始资料](https://example.com/dataset_abcdef1234)\n```python\nload("dataset_abcdef1234")\n```';
    expect(bindResearchCitations(content, [])).toBe(content);
  });
});
