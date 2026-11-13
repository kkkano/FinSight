import type { DashboardResearchContext } from '../types/chatHandoff';

/** 仅投影已选界面数据的时间与引用，不生成新的数据句柄。 */
export function dashboardResearchContext(meta: unknown, selectedMetric?: DashboardResearchContext['selectedMetric']): DashboardResearchContext {
  const value = meta && typeof meta === 'object' ? meta as Record<string, unknown> : {};
  const range = value.time_range && typeof value.time_range === 'object' ? value.time_range as Record<string, unknown> : {};
  const string = (item: unknown): string | undefined => typeof item === 'string' && item ? item : undefined;
  const dataRefs = [...new Set([...(Array.isArray(value.data_refs) ? value.data_refs.filter((item): item is string => typeof item === 'string') : []),
    ...(typeof value.data_ref === 'string' ? [value.data_ref] : [])])];
  const start = string(range.start);
  const end = string(range.end) || string(value.as_of);
  const period = string(range.period) || string(value.frequency);
  return { selectedMetric, ...(start || end || period ? { timeRange: { start, end, period } } : {}), dataRefs };
}
