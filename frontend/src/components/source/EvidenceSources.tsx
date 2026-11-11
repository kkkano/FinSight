import type { EvidenceItem } from '../../types';
import { knownSourceDisplayName, sourceDisplayName, sourceTitleDisplayName } from '../../utils/sourceDisplayName';
import { hasDataSourceDetails, SourceDetails } from './SourceDetails';
import styles from '../chat/ChatDesign.module.css';

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

export function EvidenceSources({ sources }: { sources: EvidenceItem[] }) {
  const groups = new Map<string, Array<{ source: EvidenceItem; index: number }>>();
  sources.forEach((source, index) => {
    const name = evidenceSourceGroup(source);
    groups.set(name, [...(groups.get(name) || []), { source, index }]);
  });
  return <section className={styles.sourceList} aria-label="回答来源">
    <details data-testid="answer-sources">
      <summary className={styles.sourceGroupHeading}>来源 <span>{groups.size} 类 · {sources.length} 项</span></summary>
      <div className={styles.sourceGroups}>{[...groups].map(([name, entries]) => <details key={name} data-testid="source-group">
        <summary className={styles.sourceGroupHeading}>{name}<span>{entries.length} 项</span></summary>
        <div className={styles.sourceGroupItems}>{entries.map(({ source, index }) => source.url && !hasDataSourceDetails(source)
          ? <a key={source.source_id || index} href={source.url} target="_blank" rel="noopener noreferrer" className={styles.sourceLink}>
            <span className="num text-t-accent">{index + 1}</span>
            <span className={styles.sourceArticleTitle}>{sourceTitleDisplayName(source.title, source.source || source.url)}</span>
            {source.as_of && <time className="shrink-0 text-xs text-t-text3">{source.as_of.slice(0, 10)}</time>}
          </a>
          : <SourceDetails key={source.source_id || index} source={source} index={index} className={styles.sourceLink} />)}</div>
      </details>)}</div>
    </details>
  </section>;
}
