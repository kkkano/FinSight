export type RagObservabilitySummary = {
  enabled?: boolean;
  backend?: string;
  recent_run_count_24h?: number;
  recent_fallback_count_24h?: number;
  recent_empty_hits_rate_24h?: number;
  last_run_at?: string | null;
  last_fallback_at?: string | null;
};

export const extractInspectorItems = (payload: unknown): Array<Record<string, any>> => {
  if (Array.isArray(payload)) return payload.filter(Boolean) as Array<Record<string, any>>;
  if (payload && typeof payload === 'object' && Array.isArray((payload as { items?: unknown[] }).items)) {
    return ((payload as { items?: unknown[] }).items ?? []).filter(Boolean) as Array<Record<string, any>>;
  }
  return [];
};

const toFiniteNumber = (value: unknown): number | undefined => {
  if (typeof value === 'number') return Number.isFinite(value) ? value : undefined;
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : undefined;
  }
  return undefined;
};

const toNullableString = (value: unknown): string | null => {
  if (value == null) return null;
  const text = String(value).trim();
  return text ? text : null;
};

export const buildRagObservabilitySummary = (
  statusPayload: Record<string, any>,
  ragObservabilityComponent: Record<string, any>
): {
  summary: RagObservabilitySummary;
  recentRuns: Array<Record<string, any>>;
  fallbackSummary: Array<Record<string, any>>;
} => {
  const observabilityPayload = ((statusPayload?.observability as Record<string, any> | undefined) ?? {});
  const recentRuns = extractInspectorItems(
    observabilityPayload.recent_runs ?? statusPayload?.recent_runs ?? ragObservabilityComponent?.recent_runs
  );
  const fallbackSummary = extractInspectorItems(
    observabilityPayload.fallback_summary ?? statusPayload?.fallback_summary ?? ragObservabilityComponent?.fallback_summary
  );
  const emptyHits = recentRuns.filter((item) => Number(item?.retrieval_hit_count || 0) <= 0).length;
  const explicitRunCount = toFiniteNumber(
    observabilityPayload.recent_run_count_24h ?? ragObservabilityComponent?.recent_run_count_24h
  );
  const explicitFallbackCount = toFiniteNumber(
    observabilityPayload.recent_fallback_count_24h ?? ragObservabilityComponent?.recent_fallback_count_24h
  );
  const explicitEmptyRate = toFiniteNumber(
    observabilityPayload.recent_empty_hits_rate_24h ?? ragObservabilityComponent?.recent_empty_hits_rate_24h
  );

  return {
    recentRuns,
    fallbackSummary,
    summary: {
      enabled: Boolean(observabilityPayload.enabled ?? statusPayload?.enabled ?? ragObservabilityComponent?.enabled),
      backend: String(observabilityPayload.backend ?? ragObservabilityComponent?.backend ?? ragObservabilityComponent?.status ?? statusPayload?.status ?? 'unknown'),
      recent_run_count_24h: explicitRunCount ?? recentRuns.length,
      recent_fallback_count_24h: explicitFallbackCount ?? fallbackSummary.length,
      recent_empty_hits_rate_24h: explicitEmptyRate ?? (recentRuns.length ? emptyHits / recentRuns.length : undefined),
      last_run_at: toNullableString(observabilityPayload.last_run_at ?? ragObservabilityComponent?.last_run_at ?? recentRuns[0]?.started_at),
      last_fallback_at: toNullableString(observabilityPayload.last_fallback_at ?? ragObservabilityComponent?.last_fallback_at ?? fallbackSummary[0]?.created_at ?? fallbackSummary[0]?.last_created_at),
    },
  };
};
