import { zh } from '../../locales/zh';
import { researchFailureMessage } from '../../store/researchStream';
import type { ResearchReview } from '../../types/runtime';
import styles from './ChatDesign.module.css';

export function ResearchReviewBlock({ review, answer, onRevise, disabled = false }: {
  review: ResearchReview;
  answer: string;
  onRevise?: () => void;
  disabled?: boolean;
}) {
  const findings = review.status === 'completed' ? review.findings ?? [] : [];
  const missing = review.status === 'completed' ? (review.coverage ?? []).filter((item) => !item.met) : [];
  const label = review.status === 'running' ? zh.chat.review.running
    : review.status === 'unavailable' ? researchFailureMessage(review, zh.chat.review.unavailable)
      : review.verdict === 'insufficient' ? zh.chat.review.insufficient
        : review.verdict === 'pass' && !findings.length && !missing.length ? zh.chat.review.passed : zh.chat.review.findings;
  return <aside className={styles.sourceList} aria-label={zh.chat.review.details} data-review-id={review.review_id}>
    <p role="status" className={review.status === 'completed' && review.verdict === 'pass' && !findings.length && !missing.length
      ? 'text-t-success' : 'text-t-text2'}>{label}</p>
    {findings.length > 0 && <ul className={styles.resultArticles}>{findings.map((finding, index) => <li key={index}>
      <blockquote className={styles.detailText} data-quote-offset={answer.indexOf(finding.quote)}>{finding.quote}</blockquote>
      <p>{finding.issue}</p>
      <dl className={styles.detailPairs}>
        <div className={styles.detailPair}><dt>{zh.chat.review.suggestion}</dt><dd>{finding.suggestion}</dd></div>
      </dl>
      <details className={styles.referenceDetails}><summary>{zh.chat.review.details}</summary>
        <dl className={styles.detailPairs}><div className={styles.detailPair}><dt>{zh.chat.review.evidence}</dt><dd>{finding.evidence}</dd></div></dl>
      </details>
    </li>)}</ul>}
    {missing.length > 0 && <div><p>{zh.chat.review.unmet}</p><ul>{missing.map((item, index) => <li key={index}>{item.requirement}</li>)}</ul></div>}
    {review.status === 'unavailable' && review.error_code && <details className={styles.referenceDetails}>
      <summary>{zh.chat.review.details}</summary><pre className={styles.detailText}>{review.error_code}</pre>
    </details>}
    {onRevise && review.status === 'completed' && (review.verdict !== 'pass' || findings.length > 0 || missing.length > 0)
      && <button type="button" className={styles.composerAction} disabled={disabled} onClick={onRevise}>{zh.chat.review.revise}</button>}
  </aside>;
}
