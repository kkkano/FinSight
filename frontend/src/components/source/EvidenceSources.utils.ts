import type { EvidenceItem } from '../../types';
import { knownSourceDisplayName, sourceDisplayName } from '../../utils/sourceDisplayName';

export function evidenceSourceGroup(source: EvidenceItem): string {
  const named = knownSourceDisplayName(source.source_name) || knownSourceDisplayName(source.source);
  if (named) return named;
  if (source.url) {
    try {
      const host = new URL(source.url).hostname.replace(/^www\./, '');
      if (/(^|\.)yahoo\.com$/.test(host)) return 'Yahoo Finance';
      if (/(^|\.)chartmill\.com$/.test(host)) return 'ChartMill';
      if (/(^|\.)reuters\.com$/.test(host)) return '路透社';
      return source.source_name || source.source && !source.source.includes('_') ? sourceDisplayName(source.source_name || source.source) : host;
    } catch { /* 非网址来源仍使用已保存的服务名称。 */ }
  }
  return sourceDisplayName(source.source_name || source.source);
}
