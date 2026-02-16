import type { AlertSubscription } from './types';

export type AlertFeedEvent =
  | { type: 'snapshot'; alerts: AlertSubscription[]; receivedAt: string }
  | { type: 'upsert'; alert: AlertSubscription; receivedAt: string }
  | { type: 'remove'; alertId: string; receivedAt: string }
  | { type: 'error'; message: string; receivedAt: string };

export interface AlertFeedSource {
  connect: (handler: (event: AlertFeedEvent) => void) => () => void;
  pull: () => Promise<void>;
}

export const reduceAlertFeedEvent = (
  current: AlertSubscription[],
  event: AlertFeedEvent,
): AlertSubscription[] => {
  switch (event.type) {
    case 'snapshot':
      return [...event.alerts];
    case 'upsert': {
      const next = current.filter((item) => item.id !== event.alert.id);
      next.unshift(event.alert);
      return next;
    }
    case 'remove':
      return current.filter((item) => item.id !== event.alertId);
    case 'error':
      return current;
    default:
      return current;
  }
};

interface PollingAlertFeedOptions {
  fetchAlerts: () => Promise<AlertSubscription[]>;
  pollIntervalMs?: number;
}

export const createPollingAlertFeedSource = ({
  fetchAlerts,
  pollIntervalMs = 60_000,
}: PollingAlertFeedOptions): AlertFeedSource => {
  const listeners = new Set<(event: AlertFeedEvent) => void>();
  let timer: ReturnType<typeof setInterval> | null = null;

  const emit = (event: AlertFeedEvent) => {
    listeners.forEach((handler) => handler(event));
  };

  const pull = async () => {
    try {
      const alerts = await fetchAlerts();
      emit({
        type: 'snapshot',
        alerts,
        receivedAt: new Date().toISOString(),
      });
    } catch {
      emit({
        type: 'error',
        message: '订阅加载失败',
        receivedAt: new Date().toISOString(),
      });
    }
  };

  return {
    connect: (handler) => {
      listeners.add(handler);

      if (listeners.size === 1) {
        void pull();
        timer = setInterval(() => {
          void pull();
        }, pollIntervalMs);
      }

      return () => {
        listeners.delete(handler);
        if (listeners.size === 0 && timer) {
          clearInterval(timer);
          timer = null;
        }
      };
    },
    pull,
  };
};
