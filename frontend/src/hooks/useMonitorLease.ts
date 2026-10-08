import { useEffect, useState } from 'react';
import { buildAuthHeaders } from '../api/http';
import { buildApiUrl } from '../config/runtime';
import { useStore } from '../store/useStore';

const RENEW_INTERVAL_MS = 30_000;
const MAX_ACQUIRE_RETRIES = 2;

export type MonitorLease = {
  id: string;
  session_id: string;
  symbol: string;
  lease_token: string;
  expires_at: string;
};

export type MonitorLeaseTarget = {
  sessionId: string;
  symbol: string;
};

export type MonitorLeaseTransport = {
  acquire(target: MonitorLeaseTarget): Promise<MonitorLease>;
  renew(lease: MonitorLease): Promise<void>;
  release(lease: MonitorLease): Promise<void>;
};

export const isAuthenticatedMonitorSession = (userId: string | null | undefined): boolean =>
  Boolean(String(userId || '').trim());

type TimerHandle = ReturnType<typeof globalThis.setTimeout>;
export type MonitorLeaseStatus = 'stopped' | 'starting' | 'active' | 'error';

export function createMonitorLeaseController(
  transport: MonitorLeaseTransport,
  timers = {
    setInterval: globalThis.setInterval.bind(globalThis),
    clearInterval: globalThis.clearInterval.bind(globalThis),
    setTimeout: globalThis.setTimeout.bind(globalThis),
    clearTimeout: globalThis.clearTimeout.bind(globalThis),
  },
  onStatus: (status: MonitorLeaseStatus) => void = () => undefined,
) {
  let generation = 0;
  let lease: MonitorLease | null = null;
  let renewTimer: TimerHandle | null = null;
  let retryTimer: TimerHandle | null = null;
  let renewFailures = 0;

  const clearTimers = () => {
    if (renewTimer !== null) timers.clearInterval(renewTimer);
    if (retryTimer !== null) timers.clearTimeout(retryTimer);
    renewTimer = null;
    retryTimer = null;
  };

  const releaseCurrent = () => {
    const current = lease;
    lease = null;
    if (current) void transport.release(current).catch(() => undefined);
  };

  const stop = () => {
    generation += 1;
    clearTimers();
    releaseCurrent();
    onStatus('stopped');
  };

  const start = (target: MonitorLeaseTarget | null) => {
    stop();
    const sessionId = String(target?.sessionId || '').trim();
    const symbol = String(target?.symbol || '').trim().toUpperCase();
    if (!sessionId || !symbol) return;
    onStatus('starting');

    const currentGeneration = generation;
    const normalizedTarget = { sessionId, symbol };

    const acquire = async (attempt: number): Promise<void> => {
      try {
        const acquired = await transport.acquire(normalizedTarget);
        if (generation !== currentGeneration) {
          void transport.release(acquired).catch(() => undefined);
          return;
        }
        lease = acquired;
        onStatus('active');
        renewFailures = 0;
        renewTimer = timers.setInterval(() => {
          const current = lease;
          if (!current || generation !== currentGeneration) return;
          void transport.renew(current).then(
            () => {
              if (generation !== currentGeneration) return;
              renewFailures = 0;
              onStatus('active');
            },
            () => {
              if (generation !== currentGeneration) return;
              renewFailures += 1;
              onStatus('error');
              if (renewFailures > MAX_ACQUIRE_RETRIES) {
                clearTimers();
                lease = null; // 服务端 TTL 会回收，避免网络故障时无限重试。
              }
            },
          );
        }, RENEW_INTERVAL_MS);
      } catch {
        if (generation !== currentGeneration) return;
        onStatus('error');
        if (attempt >= MAX_ACQUIRE_RETRIES) return;
        retryTimer = timers.setTimeout(() => {
          void acquire(attempt + 1);
        }, 1_000 * (attempt + 1));
      }
    };

    void acquire(0);
  };

  return { start, stop, dispose: stop };
}

const httpTransport: MonitorLeaseTransport = {
  async acquire(target) {
    const response = await fetch(buildApiUrl('/api/monitor/leases'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...await buildAuthHeaders() },
      body: JSON.stringify({ session_id: target.sessionId, symbol: target.symbol }),
    });
    if (!response.ok) throw new Error(`monitor lease acquire failed: ${response.status}`);
    const payload = await response.json() as { lease: MonitorLease };
    return payload.lease;
  },

  async renew(lease) {
    const response = await fetch(buildApiUrl(`/api/monitor/leases/${encodeURIComponent(lease.id)}`), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', ...await buildAuthHeaders() },
      body: JSON.stringify({ lease_token: lease.lease_token }),
    });
    if (!response.ok) throw new Error(`monitor lease renew failed: ${response.status}`);
  },

  async release(lease) {
    const response = await fetch(buildApiUrl(`/api/monitor/leases/${encodeURIComponent(lease.id)}`), {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json', ...await buildAuthHeaders() },
      body: JSON.stringify({ lease_token: lease.lease_token }),
      keepalive: true,
    });
    if (!response.ok && response.status !== 404) {
      throw new Error(`monitor lease release failed: ${response.status}`);
    }
  },
};

export function useMonitorLease(symbol: string): MonitorLeaseStatus {
  const sessionId = useStore((state) => state.sessionId);
  const userId = useStore((state) => state.authIdentity?.userId);
  const [status, setStatus] = useState<MonitorLeaseStatus>('stopped');

  useEffect(() => {
    if (typeof document === 'undefined') return undefined;
    const controller = createMonitorLeaseController(httpTransport, undefined, setStatus);
    const sync = () => {
      controller.start(
        document.visibilityState === 'visible' && isAuthenticatedMonitorSession(userId)
          ? { sessionId, symbol }
          : null,
      );
    };
    sync();
    document.addEventListener('visibilitychange', sync);
    return () => {
      document.removeEventListener('visibilitychange', sync);
      controller.dispose();
    };
  }, [sessionId, symbol, userId]);
  return status;
}
