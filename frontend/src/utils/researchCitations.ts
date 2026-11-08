import type { EvidenceItem } from '../types';

export const citationId = (source: EvidenceItem, index: number) => source.source_id || `source-${index + 1}`;

export function bindResearchCitations(content: string, sources: EvidenceItem[]): string {
  // 旧消息只清理可见资料编号，不修改已保存正文、代码或来源地址。
  return content.split(/(```[\s\S]*?```)/g).map((part, index) => index % 2 ? part
    : part.split(/(https?:\/\/[^\s<>）)]+)/g).map((segment, position) => position % 2 ? segment
      : segment.replace(/\[数据集\s+(?:dataset_)?[a-f0-9]{8,}\s*[，,；;]\s*来源\s*[:：]?\s*(S[a-f0-9]+)\s*\]/g, '[$1]')
        .replace(/[（(]\s*dataset_[a-zA-Z0-9_-]+\s*[）)]/g, '')
        .replace(/数据集\s+(?:dataset_)?[a-f0-9]{8,}\b/g, '研究数据')
        .replace(/\bdataset_[a-zA-Z0-9_-]+\b/g, '研究数据')
        .replace(/\[(S[a-f0-9]+)\](?!\()/g, (original, id: string) => {
          const sourceIndex = sources.findIndex((source) => source.source_id === id);
          return sourceIndex < 0 ? original : `[${sourceIndex + 1}](#research-source-${encodeURIComponent(id)})`;
        })).join('')).join('');
}
