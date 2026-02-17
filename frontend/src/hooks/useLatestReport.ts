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
  refetch: () => Promise<LatestReportData | null>;
}

interface UseLatestReportOptions {
  sourceType?: string;
  fallbackToAnySource?: boolean;
}

export function useLatestReport(
  ticker: string | null | undefined,
  options: UseLatestReportOptions = {},
): UseLatestReportReturn {
  const [data, setData] = useState<LatestReportData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const lastTickerRef = useRef<string | null>(null);

  const sessionId = useStore((s) => s.sessionId);
  const sourceType = options.sourceType?.trim() || undefined;
  const fallbackToAnySource = options.fallbackToAnySource ?? true;

  const fetchReport = useCallback(async (): Promise<LatestReportData | null> => {
    if (!ticker || !sessionId) {
      setData(null);
      return null;
    }

    setLoading(true);
    setError(null);

    try {
      let indexResult = await apiClient.listReportIndex({
        sessionId,
        ticker,
        limit: 1,
        sourceType,
      });

      if (
        sourceType
        && fallbackToAnySource
        && (!Array.isArray(indexResult?.items) || indexResult.items.length === 0)
      ) {
        indexResult = await apiClient.listReportIndex({
          sessionId,
          ticker,
          limit: 1,
        });
      }

      const items = indexResult?.items ?? [];
      if (items.length === 0) {
        setData(null);
        return null;
      }

      const reportId = items[0].report_id;
      const replay = await apiClient.getReportReplay({
        sessionId,
        reportId,
      });

      if (replay?.success && replay.report) {
        const latest: LatestReportData = {
          reportId,
          report: replay.report,
          citations: replay.citations ?? [],
        };
        setData(latest);
        return latest;
      } else {
        setData(null);
        return null;
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load report');
      setData(null);
      return null;
    } finally {
      setLoading(false);
    }
  }, [ticker, sessionId, sourceType, fallbackToAnySource]);

  useEffect(() => {
    if (ticker !== lastTickerRef.current) {
      lastTickerRef.current = ticker ?? null;
      fetchReport();
    }
  }, [ticker, fetchReport]);

  return { data, loading, error, refetch: fetchReport };
}
