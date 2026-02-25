/**
 * 报告数据解析工具函数
 *
 * 从 Workbench 页面提取的纯函数集合，用于解析、规范化和格式化报告相关数据。
 * 所有函数均为纯函数，不依赖 React 生命周期。
 */

import { asRecord } from './record';

// ==================== 接口定义 ====================

export interface VerifierClaim {
  claim: string;
  reason: string;
}

export interface QualityReason {
  code: string;
  severity: 'warn' | 'block';
  metric: string;
  actual?: unknown;
  threshold?: unknown;
  message: string;
}

export interface CitationSnippet {
  id: string;
  source: string;
  title: string;
  snippet: string;
  url?: string;
  publishedDate?: string;
}

// ==================== 基础类型转换 ====================

/** 安全地将 unknown 值转换为 string，非字符串返回空字符串 */
export function asString(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

/** 安全地将 unknown 值转换为 string[]，过滤掉空值 */
export function asStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => asString(item)).filter(Boolean);
}

/** 安全地将 unknown 值转换为 VerifierClaim[]，截断过长文本 */
export function asVerifierClaims(value: unknown): VerifierClaim[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => asRecord(item))
    .filter((item): item is Record<string, unknown> => Boolean(item))
    .map((item) => ({
      claim: asString(item.claim).slice(0, 240),
      reason: asString(item.reason).slice(0, 240) || '证据池中未找到明确支撑',
    }))
    .filter((item) => Boolean(item.claim));
}

/** 安全地将 unknown 值转换为 QualityReason[]，标准化 severity 枚举 */
export function asQualityReasons(value: unknown): QualityReason[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => asRecord(item))
    .filter((item): item is Record<string, unknown> => Boolean(item))
    .map((item) => ({
      code: asString(item.code),
      severity: (asString(item.severity) === 'block' ? 'block' : 'warn') as 'warn' | 'block',
      metric: asString(item.metric),
      actual: item.actual,
      threshold: item.threshold,
      message: asString(item.message),
    }))
    .filter((item) => Boolean(item.code));
}

// ==================== 数值规范化 ====================

/** 将 grounding rate 规范化到 [0, 1] 区间，非有效数字返回 null */
export function normalizeGroundingRate(value: unknown): number | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return null;
  }
  return Math.max(0, Math.min(1, value));
}

// ==================== 焦点提示解析 ====================

/** 根据质量缺口描述推断焦点提示关键词 */
export function resolveFocusHintFromRequirement(requirement: string): string | null {
  const lower = requirement.toLowerCase();
  if (lower.includes('10-k')) return '10-k annual report sec';
  if (lower.includes('10-q')) return '10-q quarterly report sec';
  if (lower.includes('业绩电话会') || lower.includes('纪要') || lower.includes('transcript') || lower.includes('earnings')) {
    return 'earnings transcript conference call';
  }
  if (
    lower.includes('reuters')
    || lower.includes('bloomberg')
    || lower.includes('wsj')
    || lower.includes('ft')
    || lower.includes('cnbc')
    || lower.includes('yahoo')
  ) {
    return 'reuters bloomberg wsj ft cnbc yahoo';
  }
  if (lower.includes('摘录') || lower.includes('snippet') || lower.includes('引用')) {
    return 'snippet quote excerpt';
  }
  return null;
}

/** 将焦点提示字符串拆分为小写 token 列表（至少2字符） */
export function tokenizeFocusHint(hint: string | null | undefined): string[] {
  const normalized = asString(hint).toLowerCase();
  if (!normalized) return [];
  return normalized
    .split(/[\s,，/|]+/)
    .map((token) => token.trim())
    .filter((token) => token.length >= 2);
}

// ==================== 引用片段处理 ====================

/** 从 URL 中提取域名，去掉 www. 前缀 */
export function domainFromUrl(url: string): string {
  try {
    const parsed = new URL(url);
    return parsed.hostname.replace(/^www\./i, '');
  } catch {
    return '';
  }
}

/** 从引用对象中解析出最佳来源标签 */
export function resolveSourceLabel(citation: Record<string, unknown>): string {
  const source = asString(citation.source)
    || asString(citation.name)
    || asString(citation.publisher)
    || asString(citation.media)
    || asString(citation.outlet);
  if (source) return source;

  const title = asString(citation.title);
  if (title) {
    const titleAsDomain = domainFromUrl(title);
    return titleAsDomain || title;
  }

  const url = asString(citation.url);
  if (url) return domainFromUrl(url) || url;

  const sourceId = asString(citation.source_id);
  if (sourceId) return sourceId;

  return '未知来源';
}

/** 将原始引用对象规范化为 CitationSnippet 结构 */
export function normalizeCitationSnippet(citation: Record<string, unknown>, index: number): CitationSnippet {
  const source = resolveSourceLabel(citation);
  const sourceId = asString(citation.source_id);
  const title = asString(citation.title) || source;
  const snippet = asString(citation.snippet)
    || asString(citation.quote)
    || asString(citation.summary)
    || asString(citation.text);
  const url = asString(citation.url) || undefined;
  const publishedDate = asString(citation.published_date) || undefined;

  return {
    id: sourceId || `citation-${index + 1}`,
    source,
    title,
    snippet: snippet || '[无正文摘录]',
    url,
    publishedDate,
  };
}

/** 判断某个引用片段是否匹配焦点 token（任意一个命中即可） */
export function snippetMatchesFocus(snippet: CitationSnippet, tokens: string[]): boolean {
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

/** 格式化发布日期为 MM-DD 简短格式 */
export function formatPublishedDate(value?: string): string {
  if (!value) return '--';
  const millis = Date.parse(value);
  if (!Number.isFinite(millis)) return value;
  const date = new Date(millis);
  const month = String(date.getUTCMonth() + 1).padStart(2, '0');
  const day = String(date.getUTCDate()).padStart(2, '0');
  return `${month}-${day}`;
}
