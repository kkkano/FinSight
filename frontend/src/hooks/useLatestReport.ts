/**
 * useLatestReport — Fetch the latest report for a given ticker.
 *
 * Uses the report index API to find the most recent report,
 * then loads the full ReportIR via replay API.
 */
import { useCallback, useEffect, useRef, useState } from 'react';

import { apiClient } from '../api/client';
import { useStore } from '../store/useStore';

const matchTickerLoose = (
  targetTicker: string,
  item: { ticker?: string; title?: string; summary?: string },
): boolean => {
  const upper = targetTicker.trim().toUpperCase();
  if (!upper) return false;

  const candidates = [item.ticker, item.title, item.summary]
    .map((value) => String(value || '').toUpperCase())
    .filter(Boolean);

  return candidates.some((text) => text.includes(upper));
};

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
  preferredSourceTrigger?: string;
}

export function useLatestReport(
  ticker: string | null | undefined,
  options: UseLatestReportOptions = {},
): UseLatestReportReturn {
  const [data, setData] = useState<LatestReportData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const lastTickerRef = useRef<string | null>(null);
  const requestSeqRef = useRef(0);

  const sessionId = useStore((s) => s.sessionId);
  const sourceType = options.sourceType?.trim() || undefined;
  const fallbackToAnySource = options.fallbackToAnySource ?? true;
  const preferredSourceTrigger = options.preferredSourceTrigger?.trim() || undefined;

  const fetchReport = useCallback(async (): Promise<LatestReportData | null> => {
    const requestSeq = ++requestSeqRef.current;

    if (!ticker || !sessionId) {
      if (requestSeq === requestSeqRef.current) {
        setData(null);
        setError(null);
      }
      return null;
    }

    setLoading(true);
    setError(null);

    try {
      const indexLimit = preferredSourceTrigger ? 8 : 1;

      let indexResult = await apiClient.listReportIndex({
        sessionId,
        ticker,
        limit: indexLimit,
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
          limit: indexLimit,
        });
      }

      let items = indexResult?.items ?? [];
      if (items.length === 0 && ticker) {
        const fallbackIndex = await apiClient.listReportIndex({
          sessionId,
          limit: indexLimit,
          sourceType,
        });
        const fallbackItems = fallbackIndex?.items ?? [];
        // Only use items that actually match the target ticker (loose match).
        // Never fall back to unrelated reports — that causes cross-ticker data leaks.
        items = fallbackItems.filter((item) => matchTickerLoose(ticker, item));
      }

      if (items.length === 0) {
        if (requestSeq === requestSeqRef.current) {
          setData(null);
        }
        return null;
      }

      const fetchReplay = async (reportId: string) =>
        apiClient.getReportReplay({
          sessionId,
          reportId,
        });

      let selectedReportId = items[0].report_id;
      let replay = await fetchReplay(selectedReportId);

      if (preferredSourceTrigger) {
        for (const item of items) {
          const candidateReportId = item.report_id;
          const candidateReplay = await fetchReplay(candidateReportId);
          if (!candidateReplay?.success || !candidateReplay.report) {
            continue;
          }
          const trigger = String(
            ((candidateReplay.report as Record<string, unknown>)?.meta as Record<string, unknown> | undefined)
              ?.source_trigger ?? '',
          ).trim();
          if (trigger === preferredSourceTrigger) {
            selectedReportId = candidateReportId;
            replay = candidateReplay;
            break;
          }
        }
      }

      if (replay?.success && replay.report) {
        const latest: LatestReportData = {
          reportId: selectedReportId,
          report: replay.report,
          citations: replay.citations ?? [],
        };
        if (requestSeq === requestSeqRef.current) {
          setData(latest);
        }
        return latest;
      } else {
        if (requestSeq === requestSeqRef.current) {
          setData(null);
        }
        return null;
      }
    } catch (err) {
      if (requestSeq === requestSeqRef.current) {
        setError(err instanceof Error ? err.message : 'Failed to load report');
        setData(null);
      }
      return null;
    } finally {
      if (requestSeq === requestSeqRef.current) {
        setLoading(false);
      }
    }
  }, [ticker, sessionId, sourceType, fallbackToAnySource, preferredSourceTrigger]);

  useEffect(() => {
    if (ticker !== lastTickerRef.current) {
      lastTickerRef.current = ticker ?? null;
      // Immediately clear stale data from previous ticker to prevent cross-ticker leaks
      setData(null);
      setError(null);
      fetchReport();
    }
  }, [ticker, fetchReport]);

  return { data, loading, error, refetch: fetchReport };
}
