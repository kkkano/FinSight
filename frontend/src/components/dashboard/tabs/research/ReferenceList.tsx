/**
 * ReferenceList - 引用来源与证据片段
 *
 * 支持：
 * 1) 来源聚合统计；
 * 2) 引用片段展开；
 * 3) 通过 focusHint + focusToken 一键定位“对应证据片段”。
 */
import { useEffect, useMemo, useRef, useState } from 'react';

interface ReferenceItem {
  source: string;
  url?: string;
  count: number;
}

interface CitationSnippet {
  id: string;
  source: string;
  title: string;
  snippet: string;
  url?: string;
  publishedDate?: string;
}

interface ReferenceListProps {
  citations: Record<string, unknown>[];
  focusHint?: string | null;
  focusToken?: number;
}

function asText(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function domainFromUrl(url: string): string {
  try {
    const parsed = new URL(url);
    return parsed.hostname.replace(/^www\./i, '');
  } catch {
    return '';
  }
}

function resolveSourceLabel(citation: Record<string, unknown>): string {
  const source = asText(citation.source)
    || asText(citation.name)
    || asText(citation.publisher)
    || asText(citation.media)
    || asText(citation.outlet);
  if (source) return source;

  const title = asText(citation.title);
  if (title) {
    const titleAsDomain = domainFromUrl(title);
    return titleAsDomain || title;
  }

  const url = asText(citation.url);
  if (url) return domainFromUrl(url) || url;

  const sourceId = asText(citation.source_id);
  if (sourceId) return sourceId;

  return '未知来源';
}

function aggregateCitations(citations: Record<string, unknown>[]): ReferenceItem[] {
  const map = new Map<string, ReferenceItem>();

  for (const citation of citations) {
    const source = resolveSourceLabel(citation);
    const rawUrl = asText(citation.url);
    const url = rawUrl || undefined;
    const existing = map.get(source);
    if (existing) {
      map.set(source, {
        ...existing,
        url: existing.url || url,
        count: existing.count + 1,
      });
    } else {
      map.set(source, { source, url, count: 1 });
    }
  }

  return Array.from(map.values()).sort((a, b) => b.count - a.count);
}

function normalizeCitationSnippet(citation: Record<string, unknown>, index: number): CitationSnippet {
  const source = resolveSourceLabel(citation);
  const sourceId = asText(citation.source_id);
  const title = asText(citation.title) || source;
  const snippet = asText(citation.snippet)
    || asText(citation.quote)
    || asText(citation.summary)
    || asText(citation.text);
  const url = asText(citation.url) || undefined;
  const publishedDate = asText(citation.published_date) || undefined;

  return {
    id: sourceId || `citation-${index + 1}`,
    source,
    title,
    snippet: snippet || '[无正文摘录]',
    url,
    publishedDate,
  };
}

function tokenizeFocusHint(hint: string | null | undefined): string[] {
  const normalized = asText(hint).toLowerCase();
  if (!normalized) return [];
  return normalized
    .split(/[\s,，;/|]+/)
    .map((token) => token.trim())
    .filter((token) => token.length >= 2);
}

function snippetMatchesFocus(snippet: CitationSnippet, tokens: string[]): boolean {
  if (tokens.length === 0) return true;
  const haystack = [
    snippet.source,
    snippet.title,
    snippet.snippet,
    snippet.url || '',
  ]
    .join(' ')
    .toLowerCase();
  return tokens.some((token) => haystack.includes(token));
}

function formatPublishedDate(value?: string): string {
  if (!value) return '--';
  const millis = Date.parse(value);
  if (!Number.isFinite(millis)) return value;
  const date = new Date(millis);
  const month = String(date.getUTCMonth() + 1).padStart(2, '0');
  const day = String(date.getUTCDate()).padStart(2, '0');
  return `${month}-${day}`;
}

export function ReferenceList({
  citations,
  focusHint = null,
  focusToken,
}: ReferenceListProps) {
  const [showSnippets, setShowSnippets] = useState(false);
  const snippetRef = useRef<HTMLDivElement | null>(null);

  const references = useMemo(
    () => aggregateCitations(citations || []),
    [citations],
  );
  const snippets = useMemo(
    () => (citations || []).map((citation, idx) => normalizeCitationSnippet(citation, idx)),
    [citations],
  );
  const focusTokens = useMemo(() => tokenizeFocusHint(focusHint), [focusHint]);
  const focusedSnippets = useMemo(
    () => snippets.filter((snippet) => snippetMatchesFocus(snippet, focusTokens)),
    [snippets, focusTokens],
  );

  const snippetsToDisplay = focusTokens.length > 0
    ? (focusedSnippets.length > 0 ? focusedSnippets.slice(0, 8) : snippets.slice(0, 8))
    : snippets.slice(0, 8);

  useEffect(() => {
    if (focusTokens.length > 0) {
      setShowSnippets(true);
    }
  }, [focusTokens]);

  useEffect(() => {
    if (focusToken == null) return;
    setShowSnippets(true);
    const raf = requestAnimationFrame(() => {
      snippetRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
    return () => cancelAnimationFrame(raf);
  }, [focusToken]);

  if (!citations || citations.length === 0) {
    return null;
  }

  return (
    <div className="space-y-2" id="research-reference-list">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-semibold text-fin-text">
          参考来源
          <span className="ml-2 text-xs text-fin-muted font-normal">({citations.length})</span>
        </h4>
        <button
          type="button"
          className="text-2xs text-fin-primary hover:text-fin-primary/80 transition-colors"
          onClick={() => setShowSnippets((prev) => !prev)}
          data-testid="research-reference-toggle"
        >
          {showSnippets ? '收起片段' : '展开引用片段'}
        </button>
      </div>

      <div className="bg-fin-card border border-fin-border rounded-lg divide-y divide-fin-border">
        {references.map((ref, idx) => (
          <div
            key={`ref-${idx}`}
            className="flex items-center justify-between px-4 py-2.5"
          >
            <div className="flex-1 min-w-0">
              {ref.url ? (
                <a
                  href={ref.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm text-fin-primary hover:underline truncate block"
                >
                  {ref.source}
                </a>
              ) : (
                <span className="text-sm text-fin-text truncate block">{ref.source}</span>
              )}
            </div>
            <span className="ml-3 shrink-0 text-xs text-fin-muted">
              {ref.count} 次引用
            </span>
          </div>
        ))}
      </div>

      {showSnippets && (
        <div
          ref={snippetRef}
          className="rounded-lg border border-fin-border bg-fin-card/70"
          data-testid="research-reference-snippets"
        >
          <div className="flex items-center justify-between px-3 py-2 border-b border-fin-border/60">
            <span className="text-xs font-medium text-fin-text">证据片段</span>
            {focusTokens.length > 0 && (
              <span className="text-2xs text-fin-warning">
                {focusedSnippets.length > 0
                  ? `已定位 ${focusedSnippets.length} 条相关证据`
                  : '未找到完全匹配，已展示最近证据'}
              </span>
            )}
          </div>

          <div className="divide-y divide-fin-border/60">
            {snippetsToDisplay.map((item) => {
              const focused = focusTokens.length > 0 && snippetMatchesFocus(item, focusTokens);
              return (
                <div
                  key={item.id}
                  className={`px-3 py-2 ${focused ? 'bg-fin-warning/10' : ''}`}
                  data-testid="research-reference-snippet-item"
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-xs text-fin-text truncate">{item.title}</div>
                    <span className="text-2xs text-fin-muted shrink-0">{formatPublishedDate(item.publishedDate)}</span>
                  </div>
                  <div className="mt-1 text-2xs text-fin-muted leading-relaxed">
                    {item.snippet}
                  </div>
                  <div className="mt-1 flex items-center justify-between gap-2">
                    <span className="text-2xs text-fin-muted truncate">{item.source}</span>
                    {item.url ? (
                      <a
                        href={item.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-2xs text-fin-primary hover:underline shrink-0"
                      >
                        查看原文
                      </a>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

export default ReferenceList;
