import type { EvidenceItem } from '../types';

export const citationId = (source: EvidenceItem, index: number) => source.source_id || `source-${index + 1}`;

export function bindResearchCitations(content: string, sources: EvidenceItem[]): string {
  return content.replace(/\[(S[a-f0-9]+)\](?!\()/g, (original, id: string) => {
    const index = sources.findIndex((source) => source.source_id === id);
    return index < 0 ? original : `[${index + 1}](#research-source-${encodeURIComponent(id)})`;
  });
}
