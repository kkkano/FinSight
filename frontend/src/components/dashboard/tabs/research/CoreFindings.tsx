/**
 * CoreFindings - Render report sections by type.
 *
 * Each section shows a title, summary, and optional citation block
 * with source name and quote text.
 */

interface ReportSection {
  title?: string;
  type?: string;
  summary?: string;
  content?: string;
  citations?: { source?: string; quote?: string; url?: string }[];
}

interface CoreFindingsProps {
  report: Record<string, unknown> | null;
}

function extractSections(report: Record<string, unknown>): ReportSection[] {
  // Try multiple paths for report sections
  const candidates: unknown[] = [
    report?.sections,
    report?.findings,
    report?.core_findings,
    (report?.analysis as Record<string, unknown>)?.sections,
  ];

  for (const candidate of candidates) {
    if (Array.isArray(candidate) && candidate.length > 0) {
      return candidate.map((item: unknown) => {
        const section = item as Record<string, unknown>;
        return {
          title: (section?.title as string) ?? undefined,
          type: (section?.type as string) ?? undefined,
          summary: (section?.summary as string) ?? (section?.content as string) ?? undefined,
          citations: Array.isArray(section?.citations)
            ? (section.citations as Record<string, unknown>[]).map((c) => ({
                source: (c?.source as string) ?? undefined,
                quote: (c?.quote as string) ?? (c?.text as string) ?? undefined,
                url: (c?.url as string) ?? undefined,
              }))
            : undefined,
        };
      });
    }
  }

  return [];
}

export function CoreFindings({ report }: CoreFindingsProps) {
  if (!report) return null;

  const sections = extractSections(report);
  if (sections.length === 0) return null;

  return (
    <div className="space-y-4">
      <h4 className="text-sm font-semibold text-fin-text">核心发现</h4>
      {sections.map((section, idx) => (
        <div
          key={`${section.title ?? ''}-${idx}`}
          className="bg-fin-card border border-fin-border rounded-lg p-4"
        >
          {/* Section header */}
          <div className="flex items-center gap-2 mb-2">
            {section.type ? (
              <span className="px-2 py-0.5 rounded text-2xs font-medium bg-fin-primary/10 text-fin-primary">
                {section.type}
              </span>
            ) : null}
            <h5 className="text-sm font-medium text-fin-text">
              {section.title ?? `发现 #${idx + 1}`}
            </h5>
          </div>

          {/* Summary */}
          {section.summary ? (
            <p className="text-sm text-fin-text-secondary leading-relaxed mb-3">
              {section.summary}
            </p>
          ) : null}

          {/* Citations */}
          {section.citations && section.citations.length > 0 ? (
            <div className="space-y-2">
              {section.citations.map((citation, cidx) => (
                <div
                  key={`citation-${cidx}`}
                  className="pl-3 border-l-2 border-fin-primary/30"
                >
                  {citation.quote ? (
                    <p className="text-xs text-fin-muted italic">"{citation.quote}"</p>
                  ) : null}
                  {citation.source ? (
                    <p className="text-2xs text-fin-muted mt-1">
                      -- {citation.source}
                    </p>
                  ) : null}
                </div>
              ))}
            </div>
          ) : null}
        </div>
      ))}
    </div>
  );
}

export default CoreFindings;
