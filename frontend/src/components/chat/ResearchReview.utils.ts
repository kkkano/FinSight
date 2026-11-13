import styles from './ChatDesign.module.css';

interface MarkdownNode {
  type: string;
  value?: string;
  children?: MarkdownNode[];
  position?: { start: { offset?: number }; end: { offset?: number } };
  data?: { hName: string; hProperties: { className: string } };
}

export function createReviewHighlightPlugin(source: string, quotes: string[]) {
  const ranges: Array<{ start: number; end: number }> = [];
  for (const quote of new Set(quotes.filter(Boolean))) {
    let offset = source.indexOf(quote);
    while (offset >= 0) {
      ranges.push({ start: offset, end: offset + quote.length });
      offset = source.indexOf(quote, offset + quote.length);
    }
  }
  const merged = ranges.sort((left, right) => left.start - right.start).reduce<typeof ranges>((items, range) => {
    const last = items.at(-1);
    if (last && range.start <= last.end) last.end = Math.max(last.end, range.end);
    else items.push({ ...range });
    return items;
  }, []);
  const mark = (children: MarkdownNode[]): MarkdownNode => ({ type: 'reviewHighlight', children,
    data: { hName: 'mark', hProperties: { className: `${styles.highlight} text-t-text` } } });
  const visit = (node: MarkdownNode): void => {
    if (!node.children) return;
    node.children = node.children.flatMap((child) => {
      const start = child.position?.start.offset;
      const end = child.position?.end.offset;
      if ((child.type === 'text' || child.type === 'inlineCode') && typeof child.value === 'string'
          && typeof start === 'number' && typeof end === 'number') {
        const matches = merged.filter((range) => range.start < end && range.end > start);
        if (!matches.length) return [child];
        if (matches.some((range) => range.start <= start && range.end >= end)) return [mark([child])];
        if (child.type === 'text' && source.slice(start, end) === child.value) {
          const result: MarkdownNode[] = [];
          let cursor = 0;
          for (const range of matches) {
            const left = Math.max(start, range.start) - start;
            const right = Math.min(end, range.end) - start;
            if (left > cursor) result.push({ type: 'text', value: child.value.slice(cursor, left) });
            result.push(mark([{ type: 'text', value: child.value.slice(left, right) }]));
            cursor = right;
          }
          if (cursor < child.value.length) result.push({ type: 'text', value: child.value.slice(cursor) });
          return result;
        }
      }
      visit(child);
      return [child];
    });
  };
  return () => (tree: MarkdownNode) => visit(tree);
}
