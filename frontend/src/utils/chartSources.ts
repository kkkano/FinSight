import type { EvidenceItem } from '../types';
import { knownSourceDisplayName, sourceDisplayName } from './sourceDisplayName';

interface ChartSource { name: string; provider?: string; url?: string; timestamps: string[] }
const text = (value: unknown): string => typeof value === 'string' ? value.trim() : '';
const internal = (value: string) => /^(?:get_|fetch_|read_|search_|run_|analyze_|render_|compute_|dataset_|agent_|tool_)/i.test(value)
  || /^(?:search|market_chart|derived|unknown|none|llm|system)$/i.test(value);

export function formatChartTimestamp(value?: string | null): string {
  const raw = value?.trim();
  if (!raw) return '';
  const match = /^(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)(Z|[+-]\d{2}:?\d{2})?)?$/.exec(raw);
  if (!match || !Number.isFinite(Date.parse(raw))) return '';
  const [, date, time, zone] = match;
  if (!time || (/^00:00(?::00(?:\.0+)?)?$/.test(time) && (!zone || /^(?:Z|\+00:?00)$/.test(zone)))) return date;
  return `${date} ${time}${zone ? zone === 'Z' || /^\+00:?00$/.test(zone) ? ' UTC' : ` UTC${zone}` : ''}`;
}

/** 计数真实出处，工具包装和计算方法不是新的数据来源。输入对象保持不变。 */
export function chartSources(refs: string[] | undefined, evidence: EvidenceItem[]): ChartSource[] {
  const wanted = new Set(refs ?? []);
  const entries = new Map<string, ChartSource>();
  for (const source of evidence) {
    if (!source.source_id || !wanted.has(source.source_id)) continue;
    const row = source as EvidenceItem & { provider?: string; source_name?: string; kind?: string };
    const derived = row.kind === 'derived' || /^(?:run_|analyze_|render_|compute_)/i.test(text(row.source) || text(row.source_name));
    const rawProvider = [row.provider, row.source, row.source_name].map(text).find((name) => name && !internal(name));
    const displayed = rawProvider ? sourceDisplayName(rawProvider) : knownSourceDisplayName(row.title);
    const provider = displayed && !['来源未注明', '其他数据来源'].includes(displayed) ? displayed : undefined;
    let url: string | undefined;
    let domain: string | undefined;
    try {
      const parsed = new URL(derived ? '' : row.url || '');
      if (['http:', 'https:'].includes(parsed.protocol)) { parsed.hash = ''; parsed.searchParams.sort(); url = parsed.href; domain = parsed.hostname.replace(/^www\./, ''); }
    } catch { /* 缺少公开URL时，只使用明确的provider，不猜测出处。 */ }
    if (!url && !provider) continue;
    const key = url ? `url:${url}` : `provider:${provider!.toLowerCase()}`;
    const timestamp = formatChartTimestamp(row.as_of);
    const previous = entries.get(key);
    if (previous) {
      if (provider && !previous.provider) { previous.provider = provider; previous.name = provider; }
      if (timestamp && !previous.timestamps.includes(timestamp)) previous.timestamps.push(timestamp);
    } else entries.set(key, { name: provider || domain!, provider, url, timestamps: timestamp ? [timestamp] : [] });
  }
  const urls = [...entries.values()].filter((entry) => entry.url);
  return [...entries.values()].filter((entry) => entry.url || !urls.some((url) => url.provider === entry.provider));
}
