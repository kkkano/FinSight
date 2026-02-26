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

    const run = async () => {
      setLoadingReports(true);
      try {
        const payload = await apiClient.listReportIndex({
          sessionId,
          ticker: symbol || undefined,
          limit: 12,
        });
        if (!cancelled) {
          setLatestReports(Array.isArray(payload.items) ? payload.items : []);
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
          setSelectedReport(payload.report as ReportIR);
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
