import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryObserver } from '@tanstack/react-query';

import { apiClient } from '../api/client';
import { changeWatchlist, watchlistKey, watchlistQueryOptions } from '../hooks/useWatchlist';
import { useStore } from './useStore';


describe('shared watchlist query authentication and invalidation', () => {
  let client: QueryClient;
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(apiClient, 'getConversation').mockImplementation(async (sessionId) => ({ success: true, session_id: sessionId, conversation: { messages: [] } }));
    useStore.getState().setAuthIdentity(null);
    client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  });
  afterEach(() => client.clear());

  it('does not request the protected watchlist for anonymous entry', async () => {
    const getWatchlist = vi.spyOn(apiClient, 'getWatchlist').mockResolvedValue({ items: [] });

    const observer = new QueryObserver(client, watchlistQueryOptions(undefined));
    const unsubscribe = observer.subscribe(() => {});

    expect(getWatchlist).not.toHaveBeenCalled();
    expect(observer.getCurrentResult().data).toBeUndefined();
    unsubscribe();
  });

  it('loads the authenticated user watchlist', async () => {
    useStore.getState().setAuthIdentity({ userId: 'user-1', email: null });
    const getWatchlist = vi.spyOn(apiClient, 'getWatchlist').mockResolvedValue({
      items: [{ ticker: 'aapl', note: 'Apple', added_at: '2026-07-16T00:00:00Z' }],
    });

    const payload = await client.fetchQuery(watchlistQueryOptions('user-1'));

    expect(getWatchlist).toHaveBeenCalledOnce();
    expect(payload.items[0].ticker).toBe('aapl');
    expect(client.getQueryData(watchlistKey('user-1'))).toBe(payload);
  });

  it('clears the visible watchlist immediately when the authenticated user changes', () => {
    useStore.getState().setAuthIdentity({ userId: 'alice', email: null });
    client.setQueryData(watchlistKey('alice'), { items: [{ ticker: 'AAPL', note: 'Alice only', added_at: '' }] });
    const observer = new QueryObserver(client, watchlistQueryOptions('alice', false));
    expect(observer.getCurrentResult().data?.items).toHaveLength(1);

    useStore.getState().setAuthIdentity({ userId: 'bob', email: null });

    observer.setOptions(watchlistQueryOptions('bob', false));
    expect(observer.getCurrentResult().data).toBeUndefined();
  });

  it('ignores a late watchlist response from the previous user', async () => {
    let resolveRequest!: (value: { items: Array<{ ticker: string; note: string; added_at: string }> }) => void;
    vi.spyOn(apiClient, 'getWatchlist').mockImplementation(() => new Promise((resolve) => {
      resolveRequest = resolve;
    }));
    useStore.getState().setAuthIdentity({ userId: 'alice', email: null });

    const pending = client.fetchQuery(watchlistQueryOptions('alice'));
    useStore.getState().setAuthIdentity({ userId: 'bob', email: null });
    resolveRequest({
      items: [{ ticker: 'AAPL', note: 'Alice only', added_at: '2026-07-16T00:00:00Z' }],
    });
    await pending;

    expect(client.getQueryData(watchlistKey('bob'))).toBeUndefined();
  });

  it('ignores a late watchlist mutation response after an account switch', async () => {
    let resolveRequest!: (value: { item: { ticker: string; note: string; added_at: string } }) => void;
    vi.spyOn(apiClient, 'addWatchlistItem').mockImplementation(() => new Promise((resolve) => {
      resolveRequest = resolve;
    }));
    useStore.getState().setAuthIdentity({ userId: 'alice', email: null });
    client.setQueryData(watchlistKey('bob'), { items: [{ ticker: 'MSFT', note: 'Bob only', added_at: '' }] });
    const pending = changeWatchlist(client, 'alice', 'AAPL', false);
    await vi.waitFor(() => expect(resolveRequest).toBeTypeOf('function'));
    useStore.getState().setAuthIdentity({ userId: 'bob', email: null });
    resolveRequest({
      item: { ticker: 'AAPL', note: 'Alice only', added_at: '2026-07-16T00:00:00Z' },
    });
    await pending;

    expect(client.getQueryData(watchlistKey('bob'))).toEqual({ items: [{ ticker: 'MSFT', note: 'Bob only', added_at: '' }] });
  });

  it('updates both page observers through one server query after a mutation', async () => {
    useStore.getState().setAuthIdentity({ userId: 'alice', email: null });
    let items: Array<{ ticker: string; note: string; added_at: string }> = [];
    const getWatchlist = vi.spyOn(apiClient, 'getWatchlist').mockImplementation(async () => ({ items }));
    vi.spyOn(apiClient, 'addWatchlistItem').mockImplementation(async ({ ticker }) => {
      const item = { ticker, note: '', added_at: '' };
      items = [item];
      return { item };
    });
    const today = new QueryObserver(client, watchlistQueryOptions('alice'));
    const dashboard = new QueryObserver(client, watchlistQueryOptions('alice'));
    const stopToday = today.subscribe(() => {});
    const stopDashboard = dashboard.subscribe(() => {});
    await vi.waitFor(() => expect(today.getCurrentResult().isSuccess).toBe(true));
    expect(getWatchlist).toHaveBeenCalledTimes(1);
    await changeWatchlist(client, 'alice', 'AAPL', false);
    expect(today.getCurrentResult().data?.items[0].ticker).toBe('AAPL');
    expect(dashboard.getCurrentResult().data).toBe(today.getCurrentResult().data);
    expect(getWatchlist).toHaveBeenCalledTimes(2);
    stopToday();
    stopDashboard();
  });

  it('rejects anonymous or stale-owner mutations before making a network call', async () => {
    const add = vi.spyOn(apiClient, 'addWatchlistItem');
    await expect(changeWatchlist(client, undefined, 'AAPL', false)).rejects.toThrow('请先登录');
    useStore.getState().setAuthIdentity({ userId: 'bob', email: null });
    await expect(changeWatchlist(client, 'alice', 'AAPL', false)).rejects.toThrow('账户已切换');
    expect(add).not.toHaveBeenCalled();
  });
});
