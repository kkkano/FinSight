import { queryOptions, useQuery } from '@tanstack/react-query';

import { apiClient } from '../api/client';
import { useStore } from '../store/useStore';

export const reportIndexKey = (owner: string | undefined) => ['reports', owner || 'anonymous', 'index'] as const;
export const reportDetailKey = (owner: string | undefined, reportId: string | null) =>
  ['reports', owner || 'anonymous', 'detail', reportId] as const;

export const reportIndexQueryOptions = (owner: string | undefined) => queryOptions({
  queryKey: reportIndexKey(owner),
  queryFn: ({ signal }) => apiClient.listReportIndex({ limit: 100 }, signal),
  enabled: Boolean(owner),
  retry: false,
});

export const reportDetailQueryOptions = (owner: string | undefined, reportId: string | null) => queryOptions({
  queryKey: reportDetailKey(owner, reportId),
  queryFn: ({ signal }) => apiClient.getReportReplay({ reportId: reportId! }, signal),
  enabled: Boolean(owner && reportId),
  retry: false,
});

export function useReportHistory() {
  const owner = useStore((state) => state.authIdentity?.userId);
  const query = useQuery(reportIndexQueryOptions(owner));
  return { query, items: owner ? query.data?.items ?? [] : [] };
}

export function useReportDetail(reportId: string | null) {
  const owner = useStore((state) => state.authIdentity?.userId);
  return useQuery(reportDetailQueryOptions(owner, reportId));
}
