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
});
