/**
 * useWorkbenchReport — 报告列表加载与选择管理
 *
 * 封装三段 useEffect：
 *   1. 加载最近报告列表
 *   2. 根据活跃 ticker 自动对齐选中报告
 *   3. 加载选中报告的完整内容
 */

import { useEffect, useRef, useState } from 'react';

import { apiClient, type ReportIndexItem } from '../api/client';
import type { ReportIR } from '../types/index';
import { asString } from '../utils/reportParsing';

const REPORT_LIST_CACHE_PREFIX = 'finsight-workbench-report-list';
const REPORT_DETAIL_CACHE_PREFIX = 'finsight-workbench-report-detail';
const REPORT_LIST_CACHE_TTL_MS = 3 * 60 * 1000;
const REPORT_DETAIL_CACHE_TTL_MS = 5 * 60 * 1000;

type CacheEnvelope<T> = {
  cachedAt: number;
  payload: T;
};

function buildReportListCacheKey(sessionId: string, symbol: string): string {
  const normalizedSession = String(sessionId || '').trim() || 'anonymous';
  const normalizedSymbol = String(symbol || '').trim().toUpperCase() || '__ALL__';
  return `${REPORT_LIST_CACHE_PREFIX}:${normalizedSession}:${normalizedSymbol}`;
}

function buildReportDetailCacheKey(sessionId: string, reportId: string): string {
  const normalizedSession = String(sessionId || '').trim() || 'anonymous';
  const normalizedReportId = String(reportId || '').trim() || '__NONE__';
  return `${REPORT_DETAIL_CACHE_PREFIX}:${normalizedSession}:${normalizedReportId}`;
}

function loadCachePayload<T>(key: string, ttlMs: number): T | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as CacheEnvelope<T>;
    if (!parsed || typeof parsed !== 'object') return null;
    const cachedAt = Number((parsed as { cachedAt?: number }).cachedAt || 0);
    if (!Number.isFinite(cachedAt) || cachedAt <= 0) return null;
    if (Date.now() - cachedAt > ttlMs) return null;
    return (parsed as { payload?: T }).payload ?? null;
  } catch {
    return null;
  }
}

function saveCachePayload<T>(key: string, payload: T): void {
  if (typeof window === 'undefined') return;
  try {
    const envelope: CacheEnvelope<T> = {
      cachedAt: Date.now(),
      payload,
    };
    window.localStorage.setItem(key, JSON.stringify(envelope));
  } catch {
    // ignore localStorage errors
  }
}

export interface UseWorkbenchReportReturn {
  latestReports: ReportIndexItem[];
  loadingReports: boolean;
  selectedReportId: string | null;
  setSelectedReportId: (id: string | null) => void;
  selectedReport: ReportIR | null;
  loadingSelectedReport: boolean;
  selectedReportError: string | null;
}

export function useWorkbenchReport(
  sessionId: string,
  symbol: string,
): UseWorkbenchReportReturn {
  const [latestReports, setLatestReports] = useState<ReportIndexItem[]>([]);
  const [loadingReports, setLoadingReports] = useState(false);
  const [selectedReportId, setSelectedReportId] = useState<string | null>(null);
  const [selectedReport, setSelectedReport] = useState<ReportIR | null>(null);
  const [loadingSelectedReport, setLoadingSelectedReport] = useState(false);
  const [selectedReportError, setSelectedReportError] = useState<string | null>(null);
  const replayRequestSeqRef = useRef(0);

  // Effect 1: 加载最近报告列表
  useEffect(() => {
    let cancelled = false;
    const cacheKey = buildReportListCacheKey(sessionId, symbol);
    const cached = loadCachePayload<ReportIndexItem[]>(cacheKey, REPORT_LIST_CACHE_TTL_MS);

    if (cached) {
      setLatestReports(Array.isArray(cached) ? cached : []);
      setLoadingReports(false);
      return () => {
        cancelled = true;
      };
    }

    const run = async () => {
      setLoadingReports(true);
      try {
        const payload = await apiClient.listReportIndex({
          sessionId,
          ticker: symbol || undefined,
          limit: 12,
        });
        if (!cancelled) {
          const items = Array.isArray(payload.items) ? payload.items : [];
          setLatestReports(items);
          saveCachePayload(cacheKey, items);
        }
      } catch {
        if (!cancelled) {
          setLatestReports([]);
        }
      } finally {
        if (!cancelled) {
          setLoadingReports(false);
        }
      }
    };

    run();
    return () => {
      cancelled = true;
    };
  }, [sessionId, symbol]);

  // Effect 2: 根据活跃 ticker 自动对齐选中报告
  useEffect(() => {
    if (latestReports.length === 0) {
      setSelectedReportId(null);
      setSelectedReport(null);
      return;
    }

    const activeTicker = asString(symbol).toUpperCase();
    const currentReport = latestReports.find((item) => item.report_id === selectedReportId);

    if (activeTicker) {
      if (currentReport && asString(currentReport.ticker).toUpperCase() === activeTicker) {
        return;
      }
      const preferred = latestReports.find((item) => asString(item.ticker).toUpperCase() === activeTicker);
      if (preferred) {
        setSelectedReportId(preferred.report_id);
        return;
      }
    }

    if (currentReport) {
      return;
    }

    setSelectedReportId(latestReports[0]?.report_id ?? null);
  }, [latestReports, selectedReportId, symbol]);

  // Effect 3: 加载选中报告的完整内容
  useEffect(() => {
    let cancelled = false;
    const requestSeq = ++replayRequestSeqRef.current;

    if (!selectedReportId) {
      setSelectedReport(null);
      setSelectedReportError(null);
      setLoadingSelectedReport(false);
      return () => {
        cancelled = true;
      };
    }

    const detailCacheKey = buildReportDetailCacheKey(sessionId, selectedReportId);
    const cachedReport = loadCachePayload<ReportIR>(detailCacheKey, REPORT_DETAIL_CACHE_TTL_MS);
    if (cachedReport) {
      setSelectedReport(cachedReport);
      setSelectedReportError(null);
      setLoadingSelectedReport(false);
      return () => {
        cancelled = true;
      };
    }

    const run = async () => {
      setLoadingSelectedReport(true);
      setSelectedReportError(null);

      try {
        const payload = await apiClient.getReportReplay({
          sessionId,
          reportId: selectedReportId,
        });
        if (cancelled || requestSeq !== replayRequestSeqRef.current) return;

        if (payload?.success && payload.report) {
          const report = payload.report as ReportIR;
          setSelectedReport(report);
          saveCachePayload(detailCacheKey, report);
        } else {
          setSelectedReport(null);
          setSelectedReportError('报告加载失败，请稍后重试。');
        }
      } catch (error) {
        if (cancelled || requestSeq !== replayRequestSeqRef.current) return;
        setSelectedReport(null);
        setSelectedReportError(error instanceof Error ? error.message : '报告加载失败。');
      } finally {
        if (!cancelled && requestSeq === replayRequestSeqRef.current) {
          setLoadingSelectedReport(false);
        }
      }
    };

    void run();

    return () => {
      cancelled = true;
    };
  }, [sessionId, selectedReportId]);

  return {
    latestReports,
    loadingReports,
    selectedReportId,
    setSelectedReportId,
    selectedReport,
    loadingSelectedReport,
    selectedReportError,
  };
}
