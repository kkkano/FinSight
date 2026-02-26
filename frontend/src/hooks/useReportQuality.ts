/**
 * useReportQuality — 报告质量数据解析
 *
 * 从 selectedReport 中提取并计算所有质量相关的派生状态，
 * 包括 grounding rate、quality 门槛、verifier 核查、ticker 对齐等。
 */

import { useMemo } from 'react';

import type { ReportIR } from '../types/index';
import { asRecord } from '../utils/record';
import {
  asString,
  asStringList,
  asVerifierClaims,
  asQualityReasons,
  normalizeGroundingRate,
} from '../utils/reportParsing';
import type { VerifierClaim, QualityReason } from '../utils/reportParsing';
import { isReportTickerAligned } from '../utils/ticker';

export interface UseReportQualityReturn {
  qualityState: string;
  qualityReasons: QualityReason[];
  qualityMissing: string[];
  verifierClaims: VerifierClaim[];
  citations: Record<string, unknown>[];
  groundingRate: number | null;
  showLowGroundingBanner: boolean;
  groundingRateText: string;
  blockedReasons: QualityReason[];
  showQualityBlockedBanner: boolean;
  reportTicker: string;
  activeTicker: string;
  hasTickerMismatch: boolean;
}

export function useReportQuality(
  selectedReport: ReportIR | null,
  symbol: string,
): UseReportQualityReturn {
  return useMemo(() => {
    const selectedReportRecord = asRecord(selectedReport);
    const selectedReportMeta = asRecord(selectedReportRecord?.meta);
    const selectedReportQuality = asRecord(selectedReportRecord?.report_quality)
      ?? asRecord(selectedReportMeta?.report_quality);
    const qualityState = asString(selectedReportQuality?.state).toLowerCase();
    const qualityReasons = asQualityReasons(selectedReportQuality?.reasons);
    const selectedReportHints = asRecord(selectedReportRecord?.report_hints)
      ?? asRecord(selectedReportMeta?.report_hints);
    const selectedQualityHints = asRecord(selectedReportHints?.quality);
    const selectedVerifierHints = asRecord(selectedReportHints?.verifier);
    const qualityMissingFromHints = asStringList(selectedQualityHints?.missing_requirements);
    const qualityMissingFromReasons = qualityReasons
      .filter((item) => item.code.startsWith('QUALITY_PROFILE_') || item.code.startsWith('EVIDENCE_'))
      .map((item) => item.message)
      .filter(Boolean);
    const qualityMissing = Array.from(new Set([...qualityMissingFromHints, ...qualityMissingFromReasons]));
    const verifierClaims = asVerifierClaims(selectedVerifierHints?.unsupported_claims);
    const citations = Array.isArray(selectedReportRecord?.citations)
      ? (selectedReportRecord?.citations as Record<string, unknown>[])
      : [];

    const groundingRate = normalizeGroundingRate(selectedReportRecord?.grounding_rate)
      ?? normalizeGroundingRate(asRecord(selectedReportMeta?.grounding)?.grounding_rate)
      ?? normalizeGroundingRate(asRecord(selectedReportHints?.grounding)?.grounding_rate)
      ?? normalizeGroundingRate(asRecord(selectedQualityHints?.grounding)?.grounding_rate);

    const showLowGroundingBanner = groundingRate !== null && groundingRate < 0.6;
    const groundingRateText = groundingRate !== null ? `${Math.round(groundingRate * 100)}%` : '--';
    const blockedReasons = qualityReasons.filter((item) => item.severity === 'block');
    const showQualityBlockedBanner = qualityState === 'block';
    const reportTicker = asString(selectedReportRecord?.ticker).toUpperCase();
    const activeTicker = asString(symbol).toUpperCase();
    const hasTickerMismatch = Boolean(
      activeTicker
      && reportTicker
      && !isReportTickerAligned(activeTicker, reportTicker),
    );

    return {
      qualityState,
      qualityReasons,
      qualityMissing,
      verifierClaims,
      citations,
      groundingRate,
      showLowGroundingBanner,
      groundingRateText,
      blockedReasons,
      showQualityBlockedBanner,
      reportTicker,
      activeTicker,
      hasTickerMismatch,
    };
  }, [selectedReport, symbol]);
}
