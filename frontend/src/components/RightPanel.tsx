import { useEffect, useRef, useState } from 'react';
import { useStore } from '../store/useStore';
import { useCitationNavigation } from '../store/citationNavigation';
import { extractTickers } from '../utils/ticker';
import { sourceTitleDisplayName } from '../utils/sourceDisplayName';
import { RightPanelMarket } from './right-panel/RightPanelMarket';
import { RightPanelHeader } from './right-panel/RightPanelHeader';
import styles from './right-panel/RightPanelDesign.module.css';

export function RightPanel({ onCollapse, className, symbol }: {
  onCollapse: () => void; className?: string; symbol?: string;
}) {
  const messages = useStore((state) => state.messages);
  const sessionId = useStore((state) => state.sessionId);
  const focus = useCitationNavigation((state) => state.focus);
  const [selected, setSelected] = useState<string | null>(null);
  const [highlighted, setHighlighted] = useState<string | null>(null);
  const sourceNodes = useRef(new Map<string, HTMLElement>());
  const symbols = [...new Set([symbol, ...messages.flatMap((message) => message.role === 'user'
    ? extractTickers(message.content) : [message.relatedTicker, message.report?.ticker])].filter((item): item is string => Boolean(item)))];
  const ticker = selected && symbols.includes(selected) ? selected : symbol || symbols[0];
  const latestMessage = [...messages].reverse().find((item) => item.role === 'assistant' && item.runId);
  const focusedMessage = focus?.sessionId === sessionId && focus.changedAt >= (latestMessage?.timestamp ?? 0)
    ? messages.find((item) => item.runId === focus.runId && item.role === 'assistant') : undefined;
  const message = focusedMessage || latestMessage;
  const sources = message?.evidence_pool ?? [];
  const querySymbols = extractTickers(message?.requestSnapshot?.query || '');
  const priceLevels = (message?.priceLevels ?? []).filter((level) => Number.isFinite(level.price) && level.source_block_id
    && (level.ticker ? level.ticker === ticker : querySymbols.length === 1 && querySymbols[0] === ticker));
  useEffect(() => { setSelected(null); setHighlighted(null); }, [sessionId]);
  useEffect(() => {
    if (!focus || focus.sessionId !== sessionId || (focus.runId && focus.runId !== message?.runId)) return;
    const node = sourceNodes.current.get(focus.sourceId);
    if (!node) return;
    node.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    setHighlighted(focus.sourceId);
    const timer = setTimeout(() => setHighlighted(null), 1500);
    return () => clearTimeout(timer);
  }, [focus, sessionId, message?.runId]);
  return <section data-testid="context-panel" className={`${styles.panel} ${className || ''}`}>
    <RightPanelHeader symbols={symbols} selected={ticker} onSelect={setSelected} onCollapse={onCollapse} />
    {!ticker ? <div className={styles.empty}>
      <p>聊到股票时，这里会显示走势、关键数据和参考来源。</p>
      {['看看 AAPL 一年的走势', '比较 NVDA 和 AMD', '分析 0700.HK 最近的财报'].map((query) => <button type="button" key={query}
        onClick={() => { useStore.getState().setDraft(query); onCollapse(); }}>{query}</button>)}
    </div> : <div className={styles.body}>
      <RightPanelMarket key={ticker} symbol={ticker} priceLevels={priceLevels} />
      {sources.length > 0 && <section className={styles.sources}>
        <h3 className={styles.sourceTitle}>参考来源</h3>
        {sources.map((source, index) => {
          const id = source.source_id || `source-${index + 1}`;
          const content = <><span className="num text-t-accent">{index + 1}</span><span>{sourceTitleDisplayName(source.title, source.source)}</span>
            {(source.as_of || source.published_date) && <span className={styles.sourceDate}>{(source.as_of || source.published_date)!.slice(5, 10).replace('-', '/')}</span>}</>;
          return source.url ? <a key={id} ref={(node) => { if (node) sourceNodes.current.set(id, node); else sourceNodes.current.delete(id); }}
            data-source-id={id} className={`${styles.source} ${highlighted === id ? styles.highlight : ''}`} href={source.url} target="_blank" rel="noopener noreferrer">{content}</a>
            : <div key={id} ref={(node) => { if (node) sourceNodes.current.set(id, node); else sourceNodes.current.delete(id); }}
              className={`${styles.source} ${highlighted === id ? styles.highlight : ''}`}>{content}</div>;
        })}
      </section>}
    </div>}
  </section>;
}
