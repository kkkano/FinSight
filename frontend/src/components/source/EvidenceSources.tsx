import type { EvidenceItem } from '../../types';
import { sourceTitleDisplayName } from '../../utils/sourceDisplayName';
import { SourceDetails } from './SourceDetails';
import { hasDataSourceDetails } from './SourceDetails.utils';
import styles from '../chat/ChatDesign.module.css';
import { evidenceSourceGroup } from "./EvidenceSources.utils";

export function EvidenceSources({ sources }: { sources: EvidenceItem[] }) {
  const groups = new Map<string, Array<{ source: EvidenceItem; index: number }>>();
  sources.forEach((source, index) => {
    const name = evidenceSourceGroup(source);
    groups.set(name, [...(groups.get(name) || []), { source, index }]);
  });
  return <section className={styles.sourceList} aria-label="回答来源">
    <details data-testid="answer-sources">
      <summary className={styles.sourceGroupHeading}>来源 <span>{groups.size} 类 · {sources.length} 项</span></summary>
      {sources.length <= 6 ? <div className={styles.sourceGroupItems}>{sources.map((source, index) => <EvidenceSourceEntry key={source.source_id || index} source={source} index={index} />)}</div>
      : <div className={styles.sourceGroups}>{[...groups].map(([name, entries]) => <details key={name} data-testid="source-group">
        <summary className={styles.sourceGroupHeading}>{name}<span>{entries.length} 项</span></summary>
        <div className={styles.sourceGroupItems}>{entries.map(({ source, index }) => <EvidenceSourceEntry key={source.source_id || index} source={source} index={index} />)}</div>
      </details>)}</div>}
    </details>
  </section>;
}

function EvidenceSourceEntry({ source, index }: { source: EvidenceItem; index: number }) {
  return source.url && !hasDataSourceDetails(source)
    ? <a href={source.url} target="_blank" rel="noopener noreferrer" className={styles.sourceLink}>
      <span className="num text-t-accent">{index + 1}</span>
      <span className={styles.sourceArticleTitle}>{sourceTitleDisplayName(source.title, source.source || source.url)}</span>
      <span className="shrink-0 text-xs text-t-text3">{evidenceSourceGroup(source)}</span>
      {source.as_of && <time className="shrink-0 text-xs text-t-text3">{source.as_of.slice(0, 10)}</time>}
    </a> : <SourceDetails source={source} index={index} className={styles.sourceLink} />;
}
