import { beforeEach, describe, expect, it, vi } from 'vitest';

import { apiClient } from '../api/client';
import { useDashboardStore } from './dashboardStore';
import { useStore } from './useStore';


describe('dashboardStore watchlist authentication', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    useStore.getState().setAuthIdentity(null);
    useDashboardStore.setState({
      watchlist: [],
      _isWatchlistLoaded: false,
      _isWatchlistLoading: false,
      _watchlistOwnerId: null,
    });
  });

  it('does not request the protected watchlist for anonymous entry', async () => {
    const getWatchlist = vi.spyOn(apiClient, 'getWatchlist').mockResolvedValue({ items: [] });

    await useDashboardStore.getState().initWatchlist();

    expect(getWatchlist).not.toHaveBeenCalled();
    expect(useDashboardStore.getState()).toMatchObject({
      watchlist: [],
      _isWatchlistLoaded: true,
      _isWatchlistLoading: false,
      _watchlistOwnerId: null,
    });
  });

  it('loads the authenticated user watchlist', async () => {
    useStore.getState().setAuthIdentity({ userId: 'user-1', email: null });
    const getWatchlist = vi.spyOn(apiClient, 'getWatchlist').mockResolvedValue({
      items: [{ ticker: 'aapl', note: 'Apple', added_at: '2026-07-16T00:00:00Z' }],
    });

    await useDashboardStore.getState().initWatchlist();

    expect(getWatchlist).toHaveBeenCalledOnce();
    expect(useDashboardStore.getState()).toMatchObject({
      watchlist: [{ symbol: 'AAPL', type: 'equity', name: 'Apple' }],
      _isWatchlistLoaded: true,
      _isWatchlistLoading: false,
      _watchlistOwnerId: 'user-1',
    });
  });

  it('clears the visible watchlist immediately when the authenticated user changes', () => {
    useStore.getState().setAuthIdentity({ userId: 'alice', email: null });
    useDashboardStore.setState({
      watchlist: [{ symbol: 'AAPL', type: 'equity', name: 'Apple' }],
      _isWatchlistLoaded: true,
      _isWatchlistLoading: false,
      _watchlistOwnerId: 'alice',
    });

    useStore.getState().setAuthIdentity({ userId: 'bob', email: null });

    expect(useDashboardStore.getState()).toMatchObject({
      watchlist: [],
      _isWatchlistLoaded: false,
      _isWatchlistLoading: false,
      _watchlistOwnerId: null,
    });
  });

  it('ignores a late watchlist response from the previous user', async () => {
    let resolveRequest!: (value: { items: Array<{ ticker: string; note: string; added_at: string }> }) => void;
    vi.spyOn(apiClient, 'getWatchlist').mockImplementation(() => new Promise((resolve) => {
      resolveRequest = resolve;
    }));
    useStore.getState().setAuthIdentity({ userId: 'alice', email: null });

    const pending = useDashboardStore.getState().initWatchlist();
    useStore.getState().setAuthIdentity({ userId: 'bob', email: null });
    resolveRequest({
      items: [{ ticker: 'AAPL', note: 'Alice only', added_at: '2026-07-16T00:00:00Z' }],
    });
    await pending;

    expect(useDashboardStore.getState()).toMatchObject({
      watchlist: [],
      _watchlistOwnerId: null,
    });
  });

  it('ignores a late watchlist mutation response after an account switch', async () => {
    let resolveRequest!: (value: { item: { ticker: string; note: string; added_at: string } }) => void;
    vi.spyOn(apiClient, 'addWatchlistItem').mockImplementation(() => new Promise((resolve) => {
      resolveRequest = resolve;
    }));
    useStore.getState().setAuthIdentity({ userId: 'alice', email: null });
    useDashboardStore.setState({ _watchlistOwnerId: 'alice' });

    const pending = useDashboardStore.getState().addWatchItemApi('AAPL');
    useStore.getState().setAuthIdentity({ userId: 'bob', email: null });
    resolveRequest({
      item: { ticker: 'AAPL', note: 'Alice only', added_at: '2026-07-16T00:00:00Z' },
    });
    await pending;

    expect(useDashboardStore.getState()).toMatchObject({
      watchlist: [],
      _watchlistOwnerId: null,
    });
  });
});
