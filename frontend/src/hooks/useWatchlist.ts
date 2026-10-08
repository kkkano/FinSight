import { queryOptions, useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';
import { useMemo } from 'react';
import { apiClient } from '../api/client';
import { useStore } from '../store/useStore';
import type { WatchItem } from '../types/dashboard';

export const watchlistKey = (owner: string | undefined) => ['watchlist', owner || 'anonymous'] as const;

export const watchlistQueryOptions = (owner: string | undefined, enabled = true) => queryOptions({
  queryKey: watchlistKey(owner),
  queryFn: ({ signal }) => apiClient.getWatchlist(signal),
  enabled: enabled && Boolean(owner),
});

export async function changeWatchlist(client: QueryClient, owner: string | undefined, ticker: string, remove: boolean) {
  if (!owner) throw new Error('请先登录');
  const queryKey = watchlistKey(owner);
  await client.cancelQueries({ queryKey, exact: true });
  if (useStore.getState().authIdentity?.userId !== owner) throw new Error('账户已切换');
  if (remove) await apiClient.removeWatchlistItem(ticker);
  else await apiClient.addWatchlistItem({ ticker });
  await client.invalidateQueries({ queryKey, exact: true });
}

export function useWatchlist({ enabled = true }: { enabled?: boolean } = {}) {
  const owner = useStore((state) => state.authIdentity?.userId);
  const client = useQueryClient();
  const query = useQuery(watchlistQueryOptions(owner, enabled));
  const mutation = useMutation({
    mutationFn: ({ ticker, remove }: { ticker: string; remove: boolean }) => changeWatchlist(client, owner, ticker, remove),
  });
  const watchlist = useMemo<WatchItem[]>(() => owner ? (query.data?.items ?? []).map((item) => ({
    symbol: item.ticker.trim().toUpperCase(), type: 'equity', name: item.note || item.ticker,
  })) : [], [owner, query.data]);
  return {
    query, watchlist, mutation,
    addWatchItemApi: (ticker: string) => mutation.mutateAsync({ ticker, remove: false }),
    removeWatchItemApi: (ticker: string) => mutation.mutateAsync({ ticker, remove: true }),
  };
}
