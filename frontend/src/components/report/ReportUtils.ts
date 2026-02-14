import type { ReportIR, ReportSection, ReportContent, Citation } from '../../types/index';

/* ------------------------------------------------------------------ */
/*  Anchor & text helpers                                              */
/* ------------------------------------------------------------------ */

export const normalizeAnchor = (value: string): string =>
  value.replace(/[^a-zA-Z0-9_-]/g, '-');

/** Strip markdown syntax and count only actual content characters (Chinese chars + English words + numbers). */
export const countContentChars = (markdown: string): number => {
  if (!markdown) return 0;
  const text = markdown
    .replace(/```[\s\S]*?```/g, '')       // code blocks
    .replace(/`[^`]*`/g, '')              // inline code
    .replace(/!\[[^\]]*\]\([^)]*\)/g, '') // images
    .replace(/\[[^\]]*\]\([^)]*\)/g, (m) => m.replace(/\[([^\]]*)\]\([^)]*\)/, '$1')) // links -> text
    .replace(/^#{1,6}\s+/gm, '')          // headings
    .replace(/(\*{1,3}|_{1,3})(.*?)\1/g, '$2') // bold/italic
    .replace(/~~.*?~~/g, '')              // strikethrough
    .replace(/^[\s]*[-*+]\s+/gm, '')      // unordered lists
    .replace(/^[\s]*\d+\.\s+/gm, '')      // ordered lists
    .replace(/^>+\s?/gm, '')              // blockquotes
    .replace(/---+|===+|\*\*\*+/g, '')    // horizontal rules
    .replace(/\|/g, '')                   // table pipes
    .replace(/https?:\/\/\S+/g, '')       // raw URLs (ignore for content length)
    .replace(/[:-]+/g, ' ');             // table alignment
  // Count Chinese characters + English words + numbers
  const chinese = (text.match(/[\u4e00-\u9fff\u3400-\u4dbf]/g) || []).length;
  const words = (text.match(/[a-zA-Z0-9]+/g) || []).length;
  return chinese + words;
};

/* ------------------------------------------------------------------ */
/*  Table / domain / source helpers                                    */
/* ------------------------------------------------------------------ */

export const formatTable = (table: { headers?: string[]; rows?: string[][] }): string => {
  if (!table) return '';
  const headers = table.headers || [];
  const rows = table.rows || [];
  const lines: string[] = [];
  if (headers.length > 0) {
    lines.push(headers.join(' | '));
  }
  rows.forEach((row) => {
    lines.push(row.join(' | '));
  });
  return lines.join('\n');
};

export const extractDomain = (url: string): string => {
  try {
    return new URL(url).hostname.replace('www.', '');
  } catch {
    return url;
  }
};

export const buildSourceSummary = (citations: Citation[]): { domain: string; count: number }[] => {
  const counts = new Map<string, number>();
  citations.forEach((citation) => {
    const domain = extractDomain(citation.url);
    counts.set(domain, (counts.get(domain) || 0) + 1);
  });
  return Array.from(counts.entries())
    .map(([domain, count]) => ({ domain, count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 6);
};

/* ------------------------------------------------------------------ */
/*  Evidence badge builders                                            */
/* ------------------------------------------------------------------ */

export interface BadgeInfo {
  label: string;
  tone: string;
}

export const buildEvidenceBadges = (
  citations: Citation[],
): { quality: BadgeInfo; freshness: BadgeInfo } => {
  if (!Array.isArray(citations) || citations.length === 0) {
    return {
      quality: {
        label: 'Evidence N/A',
        tone: 'bg-slate-100 text-slate-700 dark:bg-slate-700/60 dark:text-slate-200',
      },
      freshness: {
        label: 'Freshness N/A',
        tone: 'bg-slate-100 text-slate-700 dark:bg-slate-700/60 dark:text-slate-200',
      },
    };
  }

  const confidenceValues = citations
    .map((item) => (typeof item.confidence === 'number' ? item.confidence : null))
    .filter((item): item is number => item !== null);
  const avgConfidence = confidenceValues.length > 0
    ? confidenceValues.reduce((sum, value) => sum + value, 0) / confidenceValues.length
    : null;

  const freshnessValues = citations
    .map((item) => (typeof item.freshness_hours === 'number' ? item.freshness_hours : null))
    .filter((item): item is number => item !== null);
  const freshestHours = freshnessValues.length > 0 ? Math.min(...freshnessValues) : null;

  const quality: BadgeInfo = avgConfidence === null
    ? {
      label: 'Evidence Unscored',
      tone: 'bg-slate-100 text-slate-700 dark:bg-slate-700/60 dark:text-slate-200',
    }
    : avgConfidence >= 0.8
      ? {
        label: `Evidence High (${Math.round(avgConfidence * 100)}%)`,
        tone: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-200',
      }
      : avgConfidence >= 0.65
        ? {
          label: `Evidence Medium (${Math.round(avgConfidence * 100)}%)`,
          tone: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-200',
        }
        : {
          label: `Evidence Low (${Math.round(avgConfidence * 100)}%)`,
          tone: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-200',
        };

  const freshness: BadgeInfo = freshestHours === null
    ? {
      label: 'Freshness Unknown',
      tone: 'bg-slate-100 text-slate-700 dark:bg-slate-700/60 dark:text-slate-200',
    }
    : freshestHours <= 24
      ? {
        label: 'Freshness <24h',
        tone: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-200',
      }
      : freshestHours <= 72
        ? {
          label: 'Freshness <72h',
          tone: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-200',
        }
        : freshestHours <= 24 * 7
          ? {
            label: 'Freshness <7d',
            tone: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-200',
          }
          : {
            label: 'Freshness >7d',
            tone: 'bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-200',
          };

  return { quality, freshness };
};

/* ------------------------------------------------------------------ */
/*  Error classification & formatting                                  */
/* ------------------------------------------------------------------ */

export interface ClassifiedError {
  label: string;
  tone: string;
}

export const classifyReportError = (error: string): ClassifiedError => {
  const raw = String(error || '').trim();
  const lower = raw.toLowerCase();

  if (lower.includes('invalid api key') || lower.includes('invalid_api_key') || lower.includes('api key') || lower.includes('apikey') || lower.includes('unauthorized') || lower.includes('forbidden') || lower.includes('authentication') || lower.includes('permission denied') || lower.includes('401') || lower.includes('403')) {
    return { label: '\u9274\u6743\u5931\u8d25', tone: 'bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-200' };
  }
  if (lower.includes('insufficient_quota') || lower.includes('quota') || lower.includes('billing')) {
    return { label: '\u989d\u5ea6\u4e0d\u8db3', tone: 'bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-200' };
  }
  if (lower.includes('timeout')) {
    return { label: '\u8d85\u65f6', tone: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-200' };
  }
  if (lower.includes('rate limit') || lower.includes('rate limited') || lower.includes('429')) {
    return { label: '\u9650\u6d41', tone: 'bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-200' };
  }
  if (lower.includes('connection') || lower.includes('network') || lower.includes('dns') || lower.includes('econn') || lower.includes('ssl') || lower.includes('certificate') || lower.includes('enotfound') || lower.includes('refused') || lower.includes('reset by peer') || lower.includes('socket') || lower.includes('network unreachable')) {
    return { label: '\u7f51\u7edc\u5f02\u5e38', tone: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-200' };
  }
  if (lower.includes('refuse') || lower.includes('rejected') || lower.includes('policy') || lower.includes('policy violation') || lower.includes('content policy') || lower.includes('content_policy') || lower.includes('safety') || lower.includes('safety system') || lower.includes('moderation') || lower.includes('content filter') || lower.includes('blocked')) {
    return { label: '\u6a21\u578b\u62d2\u7b54', tone: 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-200' };
  }
  if (lower.includes('service unavailable') || lower.includes('502') || lower.includes('503') || lower.includes('bad gateway') || lower.includes('server error')) {
    return { label: '\u670d\u52a1\u4e0d\u53ef\u7528', tone: 'bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-200' };
  }
  if (lower.includes('not defined') || lower.includes('unavailable') || lower.includes('unreachable')) {
    return { label: '\u6570\u636e\u6e90\u5f02\u5e38', tone: 'bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-200' };
  }
  return { label: '\u8b66\u544a', tone: 'bg-slate-100 text-slate-700 dark:bg-slate-700/60 dark:text-slate-200' };
};

export const formatReportError = (error: string): string => {
  const raw = String(error || '').trim();
  if (!raw) return raw;

  const replacements: Array<[string, string]> = [
    ['fallback_synthesis_used', '\u5df2\u542f\u7528\u5156\u5e95\u5408\u6210'],
    ['timeout', '\u8d85\u65f6'],
    ['rate limit', '\u9650\u6d41'],
    ['rate limited', '\u9650\u6d41'],
  ];

  const prefixMap: Record<string, string> = {
    price: 'PriceAgent',
    news: 'NewsAgent',
    technical: 'TechnicalAgent',
    fundamental: 'FundamentalAgent',
    macro: 'MacroAgent',
    deep_search: 'DeepSearchAgent',
    forum: 'Forum',
    orchestrator: 'Orchestrator',
  };

  let output = raw;
  for (const [from, to] of replacements) {
    if (output.toLowerCase().includes(from)) {
      output = output.replace(new RegExp(from, 'ig'), to);
    }
  }

  const parts = output.split(':');
  if (parts.length > 1) {
    const prefix = parts.shift()?.trim() || '';
    const detail = parts.join(':').trim();
    const mapped = prefixMap[prefix] || prefixMap[prefix.toLowerCase()];
    if (mapped) {
      return detail ? `${mapped} ${detail}` : mapped;
    }
  }

  if (raw.toLowerCase().includes('finnhub_client') && raw.toLowerCase().includes('not defined')) {
    return '\u6570\u636e\u6e90 Finnhub \u521d\u59cb\u5316\u5931\u8d25\uff08finnhub_client \u672a\u5b9a\u4e49\uff09';
  }

  return output;
};

/* ------------------------------------------------------------------ */
/*  Section / content extraction helpers                               */
/* ------------------------------------------------------------------ */

export const pickSectionByKeywords = (sections: ReportSection[], keywords: string[]): ReportSection | undefined =>
  sections.find((section) => keywords.some((kw) => section.title.toLowerCase().includes(kw)));

export const extractTextItems = (contents: ReportContent[], limit: number = 4): string[] => {
  const items: string[] = [];
  contents.forEach((content) => {
    if (items.length >= limit) return;
    if (content.type === 'text') {
      const raw = String(content.content || '');
      raw
        .split(/\n|\u2022|\u00b7|-\s+/)
        .map((item) => item.trim())
        .filter(Boolean)
        .forEach((item) => {
          if (items.length < limit) items.push(item);
        });
    }
  });
  return items;
};

export const extractCatalystItems = (sections: ReportSection[]): string[] => {
  const section = pickSectionByKeywords(sections, ['catalyst', '\u50ac\u5316', '\u9a71\u52a8', '\u52a8\u56e0']);
  if (!section) return [];
  return extractTextItems(section.contents, 4);
};

export const extractMetrics = (sections: ReportSection[]): { label: string; value: string }[] => {
  const metrics: { label: string; value: string }[] = [];
  for (const section of sections) {
    for (const content of section.contents) {
      if (content.type === 'table') {
        const headers = content.content.headers || [];
        const rows = content.content.rows || [];
        if (rows.length > 0) {
          headers.slice(0, 4).forEach((header: string, idx: number) => {
            const value = rows[0][idx];
            if (header && value && metrics.length < 4) {
              metrics.push({ label: header, value });
            }
          });
        }
      }
    }
  }
  if (metrics.length > 0) return metrics;

  for (const section of sections) {
    for (const content of section.contents) {
      if (content.type === 'text') {
        const raw = String(content.content || '');
        const matches = raw.matchAll(/([A-Za-z\u4e00-\u9fff]{2,8})[:：]\s*([0-9][^，。\n]{0,12})/g);
        for (const match of matches) {
          if (metrics.length >= 4) break;
          metrics.push({ label: match[1], value: match[2] });
        }
      }
    }
  }
  return metrics;
};

/* ------------------------------------------------------------------ */
/*  Report message builder (for PDF export)                            */
/* ------------------------------------------------------------------ */

export const buildReportMessages = (report: ReportIR): { role: string; content: string; timestamp: string }[] => {
  const lines: string[] = [];
  const title = `${report.title} (${report.ticker})`;
  lines.push(title);
  lines.push(`Summary: ${report.summary}`);
  if (report.recommendation) {
    lines.push(`Recommendation: ${report.recommendation}`);
  }
  if (report.risks && report.risks.length > 0) {
    lines.push(`Risks: ${report.risks.join('; ')}`);
  }

  report.sections.forEach((section) => {
    lines.push('');
    lines.push(`${section.order}. ${section.title}`);
    section.contents.forEach((content) => {
      if (content.type === 'text') {
        lines.push(String(content.content));
      } else if (content.type === 'table') {
        lines.push(formatTable(content.content));
      } else if (content.type === 'chart') {
        lines.push('[Chart]');
      } else if (content.type === 'image') {
        lines.push('[Image]');
      }
      if (content.citation_refs && content.citation_refs.length > 0) {
        lines.push(`Sources: ${content.citation_refs.join(', ')}`);
      }
    });
  });

  if (report.citations && report.citations.length > 0) {
    lines.push('');
    lines.push('References:');
    report.citations.forEach((citation) => {
      lines.push(`${citation.source_id}. ${citation.title} - ${citation.url}`);
    });
  }

  return [
    {
      role: 'assistant',
      content: lines.join('\n'),
      timestamp: report.generated_at || new Date().toISOString(),
    },
  ];
};

/* ------------------------------------------------------------------ */
/*  Chart option builder                                               */
/* ------------------------------------------------------------------ */

const safeJsonParse = (value: string): any => {
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
};

const normalizeChartPayload = (payload: any): any => {
  if (!payload) return null;
  if (typeof payload === 'string') {
    const parsed = safeJsonParse(payload);
    return parsed || null;
  }
  return payload;
};

export const buildChartOption = (content: ReportContent): Record<string, any> | null => {
  const payload = normalizeChartPayload(content.content);
  if (!payload) return null;

  if (payload.option && typeof payload.option === 'object') {
    return payload.option;
  }

  if (payload.series || payload.xAxis || payload.yAxis) {
    return payload;
  }

  const chartType = (content.metadata?.chart_type || payload.chart_type || payload.type || 'line').toString();
  const labels = payload.labels || payload.categories || payload.x || [];
  const values = payload.values || payload.data || payload.y || [];

  if (Array.isArray(payload.datasets)) {
    return {
      tooltip: { trigger: 'axis' },
      grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
      xAxis: { type: 'category', data: labels },
      yAxis: { type: 'value' },
      series: payload.datasets.map((dataset: { label?: string; data?: number[] }) => ({
        type: chartType === 'bar' ? 'bar' : 'line',
        data: dataset.data || [],
        name: dataset.label || 'Series',
        smooth: chartType !== 'bar',
      })),
    };
  }

  if (chartType === 'pie' && Array.isArray(labels) && Array.isArray(values)) {
    return {
      tooltip: { trigger: 'item' },
      series: [
        {
          type: 'pie',
          radius: ['35%', '70%'],
          data: labels.map((label: string, index: number) => ({
            name: label,
            value: values[index] ?? 0,
          })),
        },
      ],
    };
  }

  if (Array.isArray(labels) && Array.isArray(values)) {
    return {
      tooltip: { trigger: 'axis' },
      grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
      xAxis: { type: 'category', data: labels },
      yAxis: { type: 'value' },
      series: [
        {
          type: chartType === 'bar' ? 'bar' : 'line',
          data: values,
          smooth: chartType !== 'bar',
        },
      ],
    };
  }

  if (Array.isArray(payload)) {
    return {
      tooltip: { trigger: 'axis' },
      grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
      xAxis: { type: 'category', data: payload.map((_: any, index: number) => index + 1) },
      yAxis: { type: 'value' },
      series: [
        {
          type: chartType === 'bar' ? 'bar' : 'line',
          data: payload,
          smooth: chartType !== 'bar',
        },
      ],
    };
  }

  return null;
};

/* ------------------------------------------------------------------ */
/*  Report hints extractor                                             */
/* ------------------------------------------------------------------ */

export interface ReportHints {
  is_compare?: boolean;
  has_conflict?: boolean;
  compare_basis?: string[];
  conflict_agents?: string[];
}

export const extractReportHints = (report: ReportIR): ReportHints => {
  const direct = (report as any).report_hints;
  if (direct && typeof direct === 'object') {
    return direct as ReportHints;
  }
  const metaHints = (report as any)?.meta?.report_hints;
  if (metaHints && typeof metaHints === 'object') {
    return metaHints as ReportHints;
  }
  return {
    is_compare: false,
    has_conflict: false,
    compare_basis: [],
    conflict_agents: [],
  };
};

/* ------------------------------------------------------------------ */
/*  Agent detail sections extractor                                    */
/* ------------------------------------------------------------------ */

export const extractAgentDetailSections = (report: ReportIR): ReportSection[] => {
  const metaSummaries = (report.meta as any)?.agent_summaries;
  if (Array.isArray(metaSummaries) && metaSummaries.length > 0) {
    return metaSummaries.map((item: any, idx: number) => ({
      title: item.title || item.agent_name || item.agent || `Agent ${idx + 1}`,
      order: idx + 1,
      agent_name: item.agent_name || item.agent || item.name,
      confidence: typeof item.confidence === 'number' ? item.confidence : undefined,
      data_sources: Array.isArray(item.data_sources) ? item.data_sources : [],
      error: Boolean(item.error),
      status: item.status,
      contents: [
        {
          type: 'text' as const,
          content: item.summary || (item.error_message ? `\u26a0\ufe0f ${item.error_message}` : item.status === 'not_run' ? '\u672a\u8fd0\u884c\uff08\u672c\u8f6e\u672a\u89e6\u53d1\u6216\u65e0\u5339\u914d\u610f\u56fe\uff09' : '\u6682\u65e0\u8f93\u51fa'),
          metadata: {
            detail_payload: {
              raw_output: item.raw_output ?? {},
              evidence_full: Array.isArray(item.evidence_full) ? item.evidence_full : [],
              trace_full: Array.isArray(item.trace_full) ? item.trace_full : [],
              report_input: item.report_input ?? {},
            },
          },
        },
      ],
    }));
  }

  return report.sections.filter((section: any) => section.agent_name && section.agent_name !== 'ForumHost');
};

/* ------------------------------------------------------------------ */
/*  Error normalization                                                */
/* ------------------------------------------------------------------ */

export interface FormattedClassifiedError {
  text: string;
  label: string;
  tone: string;
}

export const normalizeReportErrors = (report: ReportIR): {
  formattedErrors: string[];
  classifiedErrors: FormattedClassifiedError[];
  isFallback: boolean;
  warningText: string;
  shouldShowWarning: boolean;
} => {
  const reportErrors = (report as any).errors ?? report.meta?.errors ?? (report.meta as any)?.report_error;
  const normalizedErrors: string[] = Array.isArray(reportErrors)
    ? reportErrors.filter(Boolean)
    : typeof reportErrors === 'string'
      ? [reportErrors]
      : [];
  const formattedErrors = normalizedErrors.map((err) => formatReportError(String(err)));
  const classifiedErrors: FormattedClassifiedError[] = formattedErrors.map((err) => ({
    text: err,
    ...classifyReportError(err),
  }));
  const isFallback = Boolean((report as any).meta?.is_fallback);
  const warningText = isFallback
    ? '\u672c\u6b21\u4e3a\u5156\u5e95\u62a5\u544a\uff1a\u7efc\u5408\u751f\u6210\u5931\u8d25\u6216\u6570\u636e\u4e0d\u5b8c\u6574\uff0c\u5185\u5bb9\u53ef\u80fd\u504f\u6458\u8981/\u62fc\u63a5\u3002'
    : normalizedErrors.length > 0
      ? '\u62a5\u544a\u751f\u6210\u65f6\u51fa\u73b0\u90e8\u5206\u9519\u8bef\uff1a'
      : '';
  const shouldShowWarning = Boolean(warningText || formattedErrors.length > 0);

  return { formattedErrors, classifiedErrors, isFallback, warningText, shouldShowWarning };
};
