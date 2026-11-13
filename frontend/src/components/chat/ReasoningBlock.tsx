import { useEffect, useRef, useState } from 'react';
import { ChevronDown, ChevronRight, Lightbulb } from 'lucide-react';
import type { ResearchBlock } from '../../types/runtime';
import styles from './ChatDesign.module.css';
import { zh } from '../../locales/zh';

export function ReasoningBlock({ block, live = false }: {
  block: Extract<ResearchBlock, { kind: 'reasoning' }>;
  live?: boolean;
}) {
  const [expanded, setExpanded] = useState(live);
  const body = useRef<HTMLDivElement>(null);
  useEffect(() => { setExpanded(live); }, [live]);
  useEffect(() => {
    if (live && body.current) body.current.scrollTop = body.current.scrollHeight;
  }, [block.content, live]);
  if (!block.content && !live) return null;
  const title = live ? zh.chat.thinking : zh.chat.thinkingProcess;
  return <section className={styles.reasoning} data-testid="reasoning-block" data-block-id={block.id}>
    <button type="button" className={styles.reasoningToggle} aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
      <Lightbulb size={15} className={live ? 'animate-pulse' : ''} /><span>{title}{block.agent_label && ` · ${block.agent_label}`}</span>
      <span className={styles.reasoningPreview}>{!expanded ? block.content : ''}</span>
      <span className="num shrink-0 text-xs">{block.duration_ms !== undefined ? zh.chat.reasoningSeconds((block.duration_ms / 1000).toFixed(1)) : ''}</span>
      {expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
    </button>
    {expanded && <div ref={body} className={styles.reasoningText} data-testid="reasoning-content">
      {block.content}
      {block.truncated && <p className="mt-2 text-xs text-t-text3">{zh.chat.thinkingTruncated}</p>}
    </div>}
  </section>;
}
