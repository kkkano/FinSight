/**
 * AnalystRatingCard - Shows analyst consensus rating.
 *
 * Without report: derives a technical signal consensus from MA crossover + RSI + MACD.
 * With report: displays report recommendation + sentiment.
 * Color-coded: bullish=green, bearish=red, neutral=yellow.
 */
import { useMemo } from 'react';

import type { TechnicalData } from '../../../../types/dashboard';
import type { LatestReportData } from '../../../../hooks/useLatestReport';
import { CardInfoTip } from '../../../ui/CardInfoTip';

// --- Props ---

interface AnalystRatingCardProps {
  technicals?: TechnicalData | null;
  reportData?: LatestReportData | null;
}

// --- Types ---

type Signal = 'bullish' | 'bearish' | 'neutral';

interface RatingResult {
  signal: Signal;
  label: string;
  description: string;
  signals: { name: string; value: Signal }[];
}

// --- Helpers ---

const SIGNAL_STYLES: Record<Signal, { bg: string; text: string; label: string }> = {
  bullish: { bg: 'bg-fin-success/10', text: 'text-fin-success', label: '看多' },
  bearish: { bg: 'bg-fin-danger/10', text: 'text-fin-danger', label: '看空' },
  neutral: { bg: 'bg-fin-warning/10', text: 'text-fin-warning', label: '中性' },
};

function deriveTechnicalConsensus(technicals: TechnicalData | null | undefined): RatingResult {
  const signals: { name: string; value: Signal }[] = [];

  // MA crossover: EMA12 vs EMA26
  const ema12 = technicals?.ema12;
  const ema26 = technicals?.ema26;
  if (ema12 != null && ema26 != null) {
    signals.push({
      name: 'EMA交叉',
      value: ema12 > ema26 ? 'bullish' : ema12 < ema26 ? 'bearish' : 'neutral',
    });
  }

  // RSI
  const rsi = technicals?.rsi;
  if (rsi != null) {
    signals.push({
      name: 'RSI',
      value: rsi < 30 ? 'bullish' : rsi > 70 ? 'bearish' : 'neutral',
    });
  }

  // MACD histogram
  const macdHist = technicals?.macd_hist;
  if (macdHist != null) {
    signals.push({
      name: 'MACD',
      value: macdHist > 0 ? 'bullish' : macdHist < 0 ? 'bearish' : 'neutral',
    });
  }

  // Trend
  const trend = technicals?.trend;
  if (trend) {
    signals.push({
      name: '趋势',
      value: trend === 'bullish' || trend === 'uptrend' ? 'bullish'
        : trend === 'bearish' || trend === 'downtrend' ? 'bearish'
        : 'neutral',
    });
  }

  // Compute overall
  const bullCount = signals.filter((s) => s.value === 'bullish').length;
  const bearCount = signals.filter((s) => s.value === 'bearish').length;

  let overall: Signal = 'neutral';
  if (bullCount > bearCount && bullCount >= 2) overall = 'bullish';
  else if (bearCount > bullCount && bearCount >= 2) overall = 'bearish';

  return {
    signal: overall,
    label: SIGNAL_STYLES[overall].label,
    description: `${bullCount} 项看多 / ${bearCount} 项看空 / ${signals.length - bullCount - bearCount} 项中性`,
    signals,
  };
}

function extractReportRating(reportData: LatestReportData | null | undefined): RatingResult | null {
  if (!reportData?.report) return null;
  const report = reportData.report as Record<string, unknown>;
  const rec = report.recommendation ?? report.sentiment;
  if (typeof rec !== 'string') return null;

  const lower = rec.toLowerCase();
  let signal: Signal = 'neutral';
  if (lower.includes('buy') || lower.includes('bull') || lower.includes('positive')) {
    signal = 'bullish';
  } else if (lower.includes('sell') || lower.includes('bear') || lower.includes('negative')) {
    signal = 'bearish';
  }

  return {
    signal,
    label: SIGNAL_STYLES[signal].label,
    description: rec,
    signals: [],
  };
}

// --- Component ---

export function AnalystRatingCard({ technicals, reportData }: AnalystRatingCardProps) {
  const rating = useMemo(() => {
    const reportRating = extractReportRating(reportData);
    if (reportRating) return reportRating;
    return deriveTechnicalConsensus(technicals);
  }, [technicals, reportData]);

  const style = SIGNAL_STYLES[rating.signal];

  return (
    <div className="flex flex-col p-4 bg-fin-card rounded-xl border border-fin-border">
      <div className="flex items-center gap-1 text-xs font-medium text-fin-muted mb-3">
        综合信号
        <CardInfoTip content="基于 MA 交叉、RSI、MACD 信号综合判断多空共识" />
      </div>

      {/* Main rating badge */}
      <div className={`inline-flex items-center self-start px-3 py-1.5 rounded-lg text-sm font-semibold ${style.bg} ${style.text}`}>
        {rating.label}
      </div>

      <div className="text-2xs text-fin-text-secondary mt-2">
        {rating.description}
      </div>

      {/* Individual signals */}
      {rating.signals.length > 0 && (
        <div className="mt-3 space-y-1">
          {rating.signals.map((s) => {
            const ss = SIGNAL_STYLES[s.value];
            return (
              <div key={s.name} className="flex items-center justify-between text-2xs">
                <span className="text-fin-muted">{s.name}</span>
                <span className={ss.text}>{ss.label}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default AnalystRatingCard;
