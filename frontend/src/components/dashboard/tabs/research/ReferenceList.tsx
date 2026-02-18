/**
 * ReferenceList - Display report citations/references.
 *
 * Shows a list of sources with name, URL, and citation count.
 */

interface ReferenceItem {
  source: string;
  url?: string;
  count: number;
}

interface ReferenceListProps {
  citations: Record<string, unknown>[];
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
    const rawUrl = asText(citation?.url);
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

export function ReferenceList({ citations }: ReferenceListProps) {
  if (!citations || citations.length === 0) {
    return null;
  }

  const references = aggregateCitations(citations);

  return (
    <div className="space-y-2">
      <h4 className="text-sm font-semibold text-fin-text">
        参考来源
        <span className="ml-2 text-xs text-fin-muted font-normal">({citations.length})</span>
      </h4>
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
    </div>
  );
}

export default ReferenceList;
