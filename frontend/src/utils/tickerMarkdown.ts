interface MarkdownNode {
  type: string;
  value?: string;
  url?: string;
  children?: MarkdownNode[];
}

const SKIP_PARENT_TYPES = new Set(['link', 'linkReference', 'code', 'inlineCode', 'html']);

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function splitTickerText(value: string, tickers: string[]): MarkdownNode[] | null {
  if (!value || tickers.length === 0) return null;
  const alternatives = [...tickers]
    .sort((left, right) => right.length - left.length)
    .map(escapeRegExp)
    .join('|');
  const pattern = new RegExp(`(?<![A-Z0-9.^=-])(\\$?(?:${alternatives}))(?![A-Z0-9.^=-])`, 'g');
  const nodes: MarkdownNode[] = [];
  let cursor = 0;

  for (const match of value.matchAll(pattern)) {
    const index = match.index ?? 0;
    if (index > cursor) nodes.push({ type: 'text', value: value.slice(cursor, index) });
    const label = match[0];
    const ticker = label.startsWith('$') ? label.slice(1) : label;
    nodes.push({
      type: 'link',
      url: `/dashboard/${encodeURIComponent(ticker)}`,
      children: [{ type: 'text', value: label }],
    });
    cursor = index + label.length;
  }

  if (nodes.length === 0) return null;
  if (cursor < value.length) nodes.push({ type: 'text', value: value.slice(cursor) });
  return nodes;
}

function linkifyTree(node: MarkdownNode, tickers: string[]): void {
  if (!node.children || SKIP_PARENT_TYPES.has(node.type)) return;
  const nextChildren: MarkdownNode[] = [];

  for (const child of node.children) {
    if (child.type === 'text' && typeof child.value === 'string') {
      nextChildren.push(...(splitTickerText(child.value, tickers) ?? [child]));
      continue;
    }
    linkifyTree(child, tickers);
    nextChildren.push(child);
  }

  node.children = nextChildren;
}

/** 为单条消息已确认的 ticker 生成 remark 插件；不会处理代码块或已有链接。 */
export function createTickerLinkPlugin(tickers: string[]) {
  const confirmed = [...new Set(tickers.filter(Boolean))];
  return () => (tree: MarkdownNode) => linkifyTree(tree, confirmed);
}

export function tickerFromDashboardHref(href: string | undefined): string | null {
  const prefix = '/dashboard/';
  if (!href?.startsWith(prefix)) return null;
  try {
    const ticker = decodeURIComponent(href.slice(prefix.length)).trim();
    return ticker || null;
  } catch {
    return null;
  }
}
