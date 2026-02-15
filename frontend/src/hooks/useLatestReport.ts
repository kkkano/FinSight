/**
 * useLatestReport — Fetch the latest report for a given ticker.
 *
 * Uses the report index API to find the most recent report,
 * then loads the full ReportIR via replay API.
 */
import { useCallback, useEffect, useRef, useState } from 'react';

import { apiClient } from '../api/client';
import { useStore } from '../store/useStore';

export interface LatestReportData {
  reportId: string;
  report: Record<string, unknown>;
  citations: Record<string, unknown>[];
}

interface UseLatestReportReturn {
  data: LatestReportData | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

export function useLatestReport(ticker: string | null | undefined): UseLatestReportReturn {
  const [data, setData] = useState<LatestReportData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const lastTickerRef = useRef<string | null>(null);

  const sessionId = useStore((s) => s.sessionId);

  const fetchReport = useCallback(async () => {
    if (!ticker || !sessionId) {
      setData(null);
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const indexResult = await apiClient.listReportIndex({
        sessionId,
        ticker,
        limit: 1,
      });

      const items = indexResult?.items ?? [];
      if (items.length === 0) {
        setData(null);
        setLoading(false);
        return;
      }

      const reportId = items[0].report_id;
      const replay = await apiClient.getReportReplay({
        sessionId,
        reportId,
      });

      if (replay?.success && replay.report) {
        setData({
          reportId,
          report: replay.report,
          citations: replay.citations ?? [],
        });
      } else {
        setData(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load report');
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [ticker, sessionId]);

  useEffect(() => {
    if (ticker !== lastTickerRef.current) {
      lastTickerRef.current = ticker ?? null;
      fetchReport();
    }
  }, [ticker, fetchReport]);

  return { data, loading, error, refetch: fetchReport };
}
