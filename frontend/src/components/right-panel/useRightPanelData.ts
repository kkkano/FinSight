import { useCallback, useEffect, useMemo, useState } from 'react';
import { apiClient } from '../../api/client';
import { deriveUserIdFromSessionId, useStore } from '../../store/useStore';
import { useDashboardStore } from '../../store/dashboardStore';
import type {
  AlertEvent,
  AlertSubscription,
  PortfolioSummary,
  PortfolioRow,
  WatchlistItem,
} from './types';
import { parsePricePayload } from './utils';

const ALERT_LAST_SEEN_KEY = 'fs_alert_last_seen_v1';

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

const normalizeAlertEvent = (raw: any): AlertEvent => ({
  id: String(raw?.id || `ae-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`),
  ticker: String(raw?.ticker || '--').toUpperCase(),
  eventType: String(raw?.event_type || 'unknown'),
  severity: String(raw?.severity || 'medium').toLowerCase(),
  title: String(raw?.title || 'Alert'),
  message: String(raw?.message || ''),
  triggeredAt: String(raw?.triggered_at || new Date().toISOString()),
  metadata: raw?.metadata && typeof raw.metadata === 'object' ? raw.metadata : {},
});

function parseIso(value?: string | null): number {
  if (!value) return 0;
  const ts = Date.parse(value);
  return Number.isFinite(ts) ? ts : 0;
}

export function useRightPanelData() {
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);
  const [alerts, setAlerts] = useState<AlertSubscription[]>([]);
  const [alertEvents, setAlertEvents] = useState<AlertEvent[]>([]);
  const [alertsLoading, setAlertsLoading] = useState(false);
  const [alertsError, setAlertsError] = useState<string | null>(null);
  const [unreadAlertCount, setUnreadAlertCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [isPortfolioEditing, setIsPortfolioEditing] = useState(false);
  const [positionDrafts, setPositionDrafts] = useState<Record<string, string>>({});
  const dashboardWatchlist = useDashboardStore((s) => s.watchlist ?? []);

  const { subscriptionEmail, portfolioPositions, setPortfolioPosition, removePortfolioPosition, sessionId } = useStore();
  const userId = useMemo(() => deriveUserIdFromSessionId(sessionId), [sessionId]);

  const recomputeUnreadCount = useCallback((events: AlertEvent[]) => {
    const lastSeen = parseIso(localStorage.getItem(ALERT_LAST_SEEN_KEY));
    if (!lastSeen) {
      setUnreadAlertCount(events.length);
      return;
    }
    const unread = events.filter((event) => parseIso(event.triggeredAt) > lastSeen).length;
    setUnreadAlertCount(unread);
  }, []);

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

  const loadAlerts = useCallback(async () => {
    if (!subscriptionEmail) {
      setAlerts([]);
      setAlertEvents([]);
      setUnreadAlertCount(0);
      return;
    }

    try {
      setAlertsLoading(true);
      setAlertsError(null);

      const [subResponse, feedResponse] = await Promise.all([
        apiClient.listSubscriptions(subscriptionEmail),
        apiClient.listAlertFeed({ email: subscriptionEmail, limit: 50 }),
      ]);

      const subscriptions = Array.isArray(subResponse?.subscriptions)
        ? subResponse.subscriptions.map(normalizeAlert)
        : [];
      const events = Array.isArray(feedResponse?.events)
        ? feedResponse.events.map(normalizeAlertEvent)
        : [];

      setAlerts(subscriptions);
      setAlertEvents(events);
      recomputeUnreadCount(events);
      setLastUpdated(new Date());
    } catch {
      setAlertsError('告警数据加载失败');
    } finally {
      setAlertsLoading(false);
    }
  }, [subscriptionEmail, recomputeUnreadCount]);

  const refreshAll = useCallback(async () => {
    setLoading(true);
    await Promise.all([loadWatchlist(), loadAlerts()]);
    setLastUpdated(new Date());
    setLoading(false);
  }, [loadWatchlist, loadAlerts]);

  const markAlertsRead = useCallback(() => {
    localStorage.setItem(ALERT_LAST_SEEN_KEY, new Date().toISOString());
    setUnreadAlertCount(0);
  }, []);

  useEffect(() => {
    setLoading(true);
    void Promise.all([loadWatchlist(), loadAlerts()]).finally(() => setLoading(false));

    const timer = setInterval(() => {
      void Promise.all([loadWatchlist(), loadAlerts()]);
      setLastUpdated(new Date());
    }, 60_000);
    return () => clearInterval(timer);
  }, [loadWatchlist, loadAlerts]);

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
    alertEvents,
    alertsLoading,
    alertsError,
    unreadAlertCount,
    markAlertsRead,
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
