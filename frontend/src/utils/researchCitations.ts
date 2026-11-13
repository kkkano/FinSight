import type { EvidenceItem } from '../types';

type CitationSource = Omit<EvidenceItem, 'source_id'> & { source_id?: string | number };

export const citationId = (source: CitationSource, index: number): string =>
  source.source_id === undefined || source.source_id === '' ? `source-${index + 1}` : String(source.source_id);

export function bindResearchCitations(content: string, sources: CitationSource[]): string {
  // 旧消息只清理可见资料编号，不修改已保存正文、代码或来源地址。
  return content.split(/(```[\s\S]*?```|`[^`\n]*`)/g).map((part, index) => index % 2 ? part
    : part.split(/(https?:\/\/[^\s<>）)]+)/g).map((segment, position) => position % 2 ? segment
      : segment.replace(/\[数据集\s+(?:dataset_)?[a-f0-9]{8,}\s*[，,；;]\s*来源\s*[:：]?\s*(S[a-f0-9]+)\s*\]/g, '[$1]')
        .replace(/[（(]\s*dataset_[a-zA-Z0-9_-]+\s*[）)]/g, '')
        .replace(/数据集\s+(?:dataset_)?[a-f0-9]{8,}\b/g, '研究数据')
        .replace(/\bdataset_[a-zA-Z0-9_-]+\b/g, '研究数据')
        .replace(/\[(S[a-f0-9]+|\d+)\](?!\()/g, (original, id: string) => {
          // 固定引用协议按真实 source_id 绑定；整数不是来源数组的位置。
          const sourceIndex = sources.findIndex((source) => source.source_id !== undefined && String(source.source_id) === id);
          return sourceIndex < 0 ? original : `[${sourceIndex + 1}](#research-source-${encodeURIComponent(id)})`;
        })).join('')).join('');
}
