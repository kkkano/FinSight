import { useCallback, useEffect, useMemo, useState } from 'react';
import { apiClient } from '../../api/client';
import { deriveUserIdFromSessionId, useStore } from '../../store/useStore';
import { useDashboardStore } from '../../store/dashboardStore';
import { createPollingAlertFeedSource, reduceAlertFeedEvent } from './alertFeed';
import type { AlertSubscription, PortfolioSummary, PortfolioRow, WatchlistItem } from './types';
import { parsePricePayload } from './utils';

const normalizeAlert = (raw: any): AlertSubscription => {
  const ticker = String(raw?.ticker || '--').toUpperCase();
  const email = String(raw?.email || 'anonymous');
  const alertTypes = Array.isArray(raw?.alert_types)
    ? raw.alert_types.filter((value: unknown) => typeof value === 'string')
    : [];
  return {
    id: `${email}:${ticker}:${alertTypes.join('|')}`,
    ticker,
    alertTypes,
    disabled: raw?.disabled === true,
    priceThreshold: typeof raw?.price_threshold === 'number' ? raw.price_threshold : null,
    riskThreshold: typeof raw?.risk_threshold === 'string' ? raw.risk_threshold : null,
    lastAlertAt: typeof raw?.last_alert_at === 'string' ? raw.last_alert_at : null,
    updatedAt: typeof raw?.updated_at === 'string' ? raw.updated_at : null,
    source: 'polling',
  };
};

export function useRightPanelData() {
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);
  const [alerts, setAlerts] = useState<AlertSubscription[]>([]);
  const [alertsLoading, setAlertsLoading] = useState(false);
  const [alertsError, setAlertsError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [isPortfolioEditing, setIsPortfolioEditing] = useState(false);
  const [positionDrafts, setPositionDrafts] = useState<Record<string, string>>({});
  const dashboardWatchlist = useDashboardStore((s) => s.watchlist ?? []);

  const { subscriptionEmail, portfolioPositions, setPortfolioPosition, removePortfolioPosition, sessionId } = useStore();
  const userId = useMemo(() => deriveUserIdFromSessionId(sessionId), [sessionId]);

  const loadWatchlist = useCallback(async () => {
    try {
      const profile = await apiClient.getUserProfile(userId);
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
  }, [dashboardWatchlist, userId]);

  const fetchAlertSnapshot = useCallback(async (): Promise<AlertSubscription[]> => {
    if (!subscriptionEmail) return [];
    const response = await apiClient.listSubscriptions(subscriptionEmail);
    return Array.isArray(response?.subscriptions) ? response.subscriptions.map(normalizeAlert) : [];
  }, [subscriptionEmail]);

  const alertFeedSource = useMemo(
    () => createPollingAlertFeedSource({ fetchAlerts: fetchAlertSnapshot }),
    [fetchAlertSnapshot],
  );

  const refreshAll = useCallback(async () => {
    setLoading(true);
    setAlertsLoading(true);
    setAlertsError(null);
    await Promise.all([loadWatchlist(), alertFeedSource.pull()]);
    setLastUpdated(new Date());
    setLoading(false);
    setAlertsLoading(false);
  }, [loadWatchlist, alertFeedSource]);

  useEffect(() => {
    setLoading(true);
    void loadWatchlist().finally(() => setLoading(false));
    const timer = setInterval(() => {
      void loadWatchlist();
      setLastUpdated(new Date());
    }, 60_000);
    return () => clearInterval(timer);
  }, [loadWatchlist]);

  useEffect(() => {
    setAlertsLoading(true);
    setAlertsError(null);
    const unsubscribe = alertFeedSource.connect((event) => {
      if (event.type === 'error') {
        setAlertsError(event.message);
        setAlertsLoading(false);
        setLastUpdated(new Date());
        return;
      }
      setAlerts((current) => reduceAlertFeedEvent(current, event));
      setAlertsError(null);
      setAlertsLoading(false);
      setLastUpdated(new Date());
    });
    return unsubscribe;
  }, [alertFeedSource]);

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
    alertsLoading,
    alertsError,
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
