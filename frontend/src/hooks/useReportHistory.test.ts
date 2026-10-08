import { QueryClient, QueryObserver } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { apiClient } from '../api/client';
import { reportDetailKey, reportDetailQueryOptions, reportIndexQueryOptions } from './useReportHistory';

describe('account report queries', () => {
  let client: QueryClient;
  beforeEach(() => { client = new QueryClient(); });
  afterEach(() => { client.clear(); vi.restoreAllMocks(); });

  it('reads the account directory including reports from multiple sessions', async () => {
    const list = vi.spyOn(apiClient, 'listReportIndex').mockResolvedValue({ session_id: '', count: 2, items: [
      { report_id: 'first', session_id: 'session-1' }, { report_id: 'second', session_id: 'session-2' },
    ] });
    const result = await client.fetchQuery(reportIndexQueryOptions('alice'));
    expect(list.mock.calls[0][0]).toEqual({ limit: 100 });
    expect(result.items.map((item) => item.session_id)).toEqual(['session-1', 'session-2']);
  });

  it('retries the same failed detail without refetching a successful directory', async () => {
    const replay = vi.spyOn(apiClient, 'getReportReplay').mockRejectedValueOnce(new Error('detail unavailable'))
      .mockResolvedValueOnce({ session_id: 'session-2', report: { report_id: 'second' }, citations: [], trace_digest: {} });
    const list = vi.spyOn(apiClient, 'listReportIndex').mockResolvedValue({ session_id: '', count: 1, items: [
      { report_id: 'second', session_id: 'session-2' },
    ] });
    await client.fetchQuery(reportIndexQueryOptions('alice'));
    const observer = new QueryObserver(client, reportDetailQueryOptions('alice', 'second'));
    const stop = observer.subscribe(() => {});
    await vi.waitFor(() => expect(observer.getCurrentResult().isError).toBe(true));
    await observer.refetch();
    expect(observer.getCurrentResult().data?.report.report_id).toBe('second');
    expect(replay).toHaveBeenCalledTimes(2);
    expect(list).toHaveBeenCalledTimes(1);
    stop();
  });

  it('does not show a previous owner detail after account changes', () => {
    client.setQueryData(reportDetailKey('alice', 'first'), { report: { report_id: 'first' } });
    const observer = new QueryObserver(client, { ...reportDetailQueryOptions('alice', 'first'), enabled: false });
    expect(observer.getCurrentResult().data?.report.report_id).toBe('first');
    observer.setOptions({ ...reportDetailQueryOptions('bob', 'first'), enabled: false });
    expect(observer.getCurrentResult().data).toBeUndefined();
  });
});
