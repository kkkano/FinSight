import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  createMonitorLeaseController,
  isAuthenticatedMonitorSession,
  type MonitorLease,
  type MonitorLeaseTransport,
} from './useMonitorLease';

const lease: MonitorLease = {
  id: 'lease-1',
  session_id: 'session-1',
  symbol: 'AAPL',
  lease_token: 'secret-token-value',
  expires_at: '2026-07-11T00:01:30Z',
};

const flush = async () => {
  await Promise.resolve();
  await Promise.resolve();
};

afterEach(() => {
  vi.useRealTimers();
});

describe('monitor page lease lifecycle', () => {
  it('only enables authenticated monitor sessions', () => {
    expect(isAuthenticatedMonitorSession(undefined)).toBe(false);
    expect(isAuthenticatedMonitorSession('')).toBe(false);
    expect(isAuthenticatedMonitorSession('user-1')).toBe(true);
  });

  it('acquires, renews every 30 seconds, and releases only its own lease', async () => {
    vi.useFakeTimers();
    const transport: MonitorLeaseTransport = {
      acquire: vi.fn().mockResolvedValue(lease),
      renew: vi.fn().mockResolvedValue(undefined),
      release: vi.fn().mockResolvedValue(undefined),
    };
    const controller = createMonitorLeaseController(transport);

    controller.start({ sessionId: 'session-1', symbol: 'aapl' });
    await flush();
    expect(transport.acquire).toHaveBeenCalledWith({ sessionId: 'session-1', symbol: 'AAPL' });

    await vi.advanceTimersByTimeAsync(30_000);
    expect(transport.renew).toHaveBeenCalledWith(lease);

    controller.stop();
    await flush();
    expect(transport.release).toHaveBeenCalledTimes(1);
    expect(transport.release).toHaveBeenCalledWith(lease);
  });

  it('releases the previous page instance when symbol changes', async () => {
    const second = { ...lease, id: 'lease-2', symbol: 'MSFT', lease_token: 'second-token-value' };
    const transport: MonitorLeaseTransport = {
      acquire: vi.fn().mockResolvedValueOnce(lease).mockResolvedValueOnce(second),
      renew: vi.fn().mockResolvedValue(undefined),
      release: vi.fn().mockResolvedValue(undefined),
    };
    const controller = createMonitorLeaseController(transport);

    controller.start({ sessionId: 'session-1', symbol: 'AAPL' });
    await flush();
    controller.start({ sessionId: 'session-1', symbol: 'MSFT' });
    await flush();

    expect(transport.release).toHaveBeenCalledTimes(1);
    expect(transport.release).toHaveBeenCalledWith(lease);
    controller.dispose();
  });

  it('limits acquisition retries after network failure', async () => {
    vi.useFakeTimers();
    const transport: MonitorLeaseTransport = {
      acquire: vi.fn().mockRejectedValue(new Error('offline')),
      renew: vi.fn(),
      release: vi.fn(),
    };
    const controller = createMonitorLeaseController(transport);

    controller.start({ sessionId: 'session-1', symbol: 'AAPL' });
    await flush();
    await vi.runAllTimersAsync();

    expect(transport.acquire).toHaveBeenCalledTimes(3);
    expect(transport.renew).not.toHaveBeenCalled();
    expect(transport.release).not.toHaveBeenCalled();
  });
});
