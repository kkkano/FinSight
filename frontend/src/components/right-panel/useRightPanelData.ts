import { useCallback, useEffect, useMemo, useState } from 'react';
import { apiClient } from '../../api/client';
import { useStore } from '../../store/useStore';
import { useDashboardStore } from '../../store/dashboardStore';
import type { PortfolioSummary, PortfolioRow, WatchlistItem } from './types';
import { parsePricePayload } from './utils';

const DEFAULT_USER_ID = 'default_user';

export function useRightPanelData() {
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);
  const [alerts, setAlerts] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [isPortfolioEditing, setIsPortfolioEditing] = useState(false);
  const [positionDrafts, setPositionDrafts] = useState<Record<string, string>>({});
  const dashboardWatchlist = useDashboardStore((s) => s.watchlist ?? []);

  const { subscriptionEmail, portfolioPositions, setPortfolioPosition, removePortfolioPosition } = useStore();

  const loadWatchlist = useCallback(async () => {
    try {
      const profile = await apiClient.getUserProfile(DEFAULT_USER_ID);
      const listFromProfile = Array.isArray(profile?.profile?.watchlist) ? profile.profile.watchlist : [];
      const list = listFromProfile.length
        ? listFromProfile
        : dashboardWatchlist.map((item) => item.symbol).filter(Boolean);
      if (!list.length) {
        setWatchlist([]);
        return;
      }

      const results = await Promise.all(
        list.map(async (ticker: string) => {
          try {
            const response = await apiClient.fetchStockPrice(ticker);
            const payload = response?.data ?? response;
            const parsed = parsePricePayload(payload?.data ?? payload);
            return { ticker, label: ticker, ...parsed } as WatchlistItem;
          } catch {
            return { ticker, label: ticker } as WatchlistItem;
          }
        }),
      );
      setWatchlist(results);
    } catch {
      setWatchlist([]);
    }
  }, [dashboardWatchlist]);

  const loadAlerts = useCallback(async () => {
    if (!subscriptionEmail) {
      setAlerts([]);
      return;
    }
    try {
      const response = await apiClient.listSubscriptions(subscriptionEmail);
      setAlerts(Array.isArray(response?.subscriptions) ? response.subscriptions : []);
    } catch {
      setAlerts([]);
    }
  }, [subscriptionEmail]);

  const refreshAll = useCallback(async () => {
    setLoading(true);
    await Promise.all([loadWatchlist(), loadAlerts()]);
    setLastUpdated(new Date());
    setLoading(false);
  }, [loadWatchlist, loadAlerts]);

  useEffect(() => {
    refreshAll();
    const timer = setInterval(refreshAll, 60_000);
    return () => clearInterval(timer);
  }, [refreshAll]);

  const positionRows = useMemo<PortfolioRow[]>(() => {
    return watchlist.map((item) => {
      const key = item.ticker.trim().toUpperCase();
      const shares = portfolioPositions[key] || 0;
      const price = typeof item.price === 'number' ? item.price : undefined;
      const change = typeof item.change === 'number' ? item.change : undefined;
      const changePct = typeof item.changePct === 'number' ? item.changePct : undefined;
      const value = price !== undefined ? price * shares : 0;
      const dayChange =
        change !== undefined
          ? change * shares
          : price !== undefined && changePct !== undefined
            ? (price * shares * changePct) / 100
            : 0;
      return { ...item, ticker: key, shares, value, dayChange };
    });
  }, [watchlist, portfolioPositions]);

  const portfolioSummary = useMemo<PortfolioSummary | null>(() => {
    const holdings = positionRows.filter((item) => item.shares > 0);
    if (!holdings.length) return null;
    const totalValue = holdings.reduce((sum, item) => sum + item.value, 0);
    const dayChange = holdings.reduce((sum, item) => sum + item.dayChange, 0);
    const avgChange = totalValue ? (dayChange / totalValue) * 100 : 0;
    return { holdings, holdingsCount: holdings.length, totalValue, dayChange, avgChange };
  }, [positionRows]);

  const startPortfolioEdit = () => {
    const drafts = watchlist.reduce<Record<string, string>>((acc, item) => {
      const key = item.ticker.trim().toUpperCase();
      const shares = portfolioPositions[key];
      acc[key] = shares ? String(shares) : '';
      return acc;
    }, {});
    setPositionDrafts(drafts);
    setIsPortfolioEditing(true);
  };

  const cancelPortfolioEdit = () => {
    setIsPortfolioEditing(false);
    setPositionDrafts({});
  };

  const savePortfolioEdit = () => {
    watchlist.forEach((item) => {
      const key = item.ticker.trim().toUpperCase();
      const raw = positionDrafts[key];
      const value = Number(raw);
      if (Number.isFinite(value) && value > 0) {
        setPortfolioPosition(key, value);
      } else if (raw !== undefined) {
        removePortfolioPosition(key);
      }
    });
    setIsPortfolioEditing(false);
  };

  return {
    watchlist,
    alerts,
    loading,
    lastUpdated,
    refreshAll,
    positionRows,
    portfolioSummary,
    isPortfolioEditing,
    positionDrafts,
    setPositionDrafts,
    startPortfolioEdit,
    cancelPortfolioEdit,
    savePortfolioEdit,
  };
}


