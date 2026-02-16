/**
 * ScoreRing - SVG ring progress chart showing composite score (1-10).
 *
 * Without report: computes a baseline score from valuation + technicals.
 * With report: uses the report confidence_score.
 */
import { useMemo } from 'react';

import type { ValuationData, TechnicalData } from '../../../../types/dashboard';
import type { LatestReportData } from '../../../../hooks/useLatestReport';

// --- Props ---

interface ScoreRingProps {
  valuation?: ValuationData | null;
  technicals?: TechnicalData | null;
  reportData?: LatestReportData | null;
}

// --- Helpers ---

/** Compute a baseline score (1-10) from valuation + technicals data */
function computeBaselineScore(
  valuation: ValuationData | null | undefined,
  technicals: TechnicalData | null | undefined,
): number {
  let score = 4; // neutral baseline

  const pe = valuation?.trailing_pe;
  if (pe !== null && pe !== undefined && pe > 0 && pe < 35) score += 2;
  else if (pe !== null && pe !== undefined && pe >= 35) score += 0;

  const trend = technicals?.trend;
  if (trend === 'bullish' || trend === 'uptrend') score += 2;
  else if (trend === 'bearish' || trend === 'downtrend') score -= 1;

  const rsi = technicals?.rsi;
  if (rsi !== null && rsi !== undefined && rsi > 30 && rsi < 70) score += 1;

  const beta = valuation?.beta;
  if (beta !== null && beta !== undefined && beta < 1.5) score += 1;

  return Math.max(1, Math.min(10, score));
}

/** Extract confidence score from report data */
function extractReportScore(reportData: LatestReportData | null | undefined): number | null {
  if (!reportData?.report) return null;
  const report = reportData.report as Record<string, unknown>;
  const confidence = report.confidence_score ?? report.score ?? report.overall_score;
  if (typeof confidence === 'number' && Number.isFinite(confidence)) {
    if (confidence <= 1) {
      return Math.max(1, Math.min(10, Math.round(confidence * 10)));
    }
    return Math.max(1, Math.min(10, Math.round(confidence)));
  }
  return null;
}

// --- Constants ---

const RING_RADIUS = 52;
const RING_STROKE = 8;
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS;

// --- Component ---

export function ScoreRing({ valuation, technicals, reportData }: ScoreRingProps) {
  const { score, fromReport } = useMemo(() => {
    const reportScore = extractReportScore(reportData);
    if (reportScore !== null) {
      return { score: reportScore, fromReport: true };
    }
    return { score: computeBaselineScore(valuation, technicals), fromReport: false };
  }, [valuation, technicals, reportData]);

  const progress = score / 10;
  const strokeDashoffset = RING_CIRCUMFERENCE * (1 - progress);

  // Color based on score
  const ringColor =
    score >= 7 ? 'text-fin-success' : score >= 4 ? 'text-fin-warning' : 'text-fin-danger';

  return (
    <div className="flex flex-col items-center justify-center p-4 bg-fin-card rounded-xl border border-fin-border">
      <div className="text-xs font-medium text-fin-muted mb-3">
        综合评分
      </div>
      <div className="relative w-32 h-32">
        <svg className="w-full h-full -rotate-90" viewBox="0 0 128 128">
          {/* Background ring */}
          <circle
            cx="64" cy="64" r={RING_RADIUS}
            fill="none"
            strokeWidth={RING_STROKE}
            className="stroke-fin-border"
          />
          {/* Progress ring */}
          <circle
            cx="64" cy="64" r={RING_RADIUS}
            fill="none"
            strokeWidth={RING_STROKE}
            strokeLinecap="round"
            strokeDasharray={RING_CIRCUMFERENCE}
            strokeDashoffset={strokeDashoffset}
            className={`${ringColor} stroke-current transition-all duration-700`}
          />
        </svg>
        {/* Score text */}
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className={`text-3xl font-bold ${ringColor}`}>{score}</span>
          <span className="text-2xs text-fin-muted">/10</span>
        </div>
      </div>
      <div className="text-2xs text-fin-muted mt-2" title={fromReport ? '' : '基于实时市场数据自动计算'}>
        {fromReport ? '基于研报评分' : '基于实时数据'}
      </div>
    </div>
  );
}

export default ScoreRing;
