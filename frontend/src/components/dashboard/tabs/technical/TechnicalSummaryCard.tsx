/**
 * TechnicalSummaryCard - Overall technical assessment display.
 *
 * Shows Bullish/Bearish/Neutral rating with signal count breakdown.
 * Derives from dashboardData.technicals.
 */
import { useMemo } from 'react';

import type { TechnicalData } from '../../../../types/dashboard';
import { DashboardSourceBadge } from '../../DashboardSourceBadge';

// --- Props ---

interface TechnicalSummaryCardProps {
  technicals?: TechnicalData | null;
}

// --- Types ---

type TechSignal = 'buy' | 'sell' | 'neutral';
type TechVerdict = 'bullish' | 'bearish' | 'neutral';

interface SignalCount {
  buy: number;
  sell: number;
  neutral: number;
}

interface SummaryResult {
  verdict: TechVerdict;
  label: string;
  counts: SignalCount;
  trend: string;
  momentum: string;
}

// --- Helpers ---

const VERDICT_STYLES: Record<TechVerdict, { bg: string; text: string }> = {
  bullish: { bg: 'bg-fin-success/10', text: 'text-fin-success' },
  bearish: { bg: 'bg-fin-danger/10', text: 'text-fin-danger' },
  neutral: { bg: 'bg-fin-warning/10', text: 'text-fin-warning' },
};
const TREND_LABELS: Record<string, string> = { bullish: '上行', bearish: '下行', neutral: '横盘' };
const MOMENTUM_LABELS: Record<string, string> = { bullish: '偏强', bearish: '偏弱', neutral: '中性' };

function computeSummary(technicals: TechnicalData | null | undefined): SummaryResult {
  if (!technicals) {
    return {
      verdict: 'neutral',
      label: '数据不足',
      counts: { buy: 0, sell: 0, neutral: 0 },
      trend: '--',
      momentum: '--',
    };
  }

  const signals: TechSignal[] = [];
  const close = technicals.close;

  // MA signals
  const mas: { value: number | null | undefined }[] = [
    { value: technicals.ma5 },
    { value: technicals.ma10 },
    { value: technicals.ma20 },
    { value: technicals.ma50 },
    { value: technicals.ma100 },
    { value: technicals.ma200 },
  ];

  for (const ma of mas) {
    if (close != null && ma.value != null) {
      signals.push(close > ma.value ? 'buy' : 'sell');
    }
  }

  // EMA signals
  if (close != null && technicals.ema12 != null) {
    signals.push(close > technicals.ema12 ? 'buy' : 'sell');
  }
  if (close != null && technicals.ema26 != null) {
    signals.push(close > technicals.ema26 ? 'buy' : 'sell');
  }

  // RSI
  if (technicals.rsi != null) {
    signals.push(technicals.rsi < 30 ? 'buy' : technicals.rsi > 70 ? 'sell' : 'neutral');
  }

  // MACD histogram
  if (technicals.macd_hist != null) {
    signals.push(technicals.macd_hist > 0 ? 'buy' : technicals.macd_hist < 0 ? 'sell' : 'neutral');
  }

  // Stoch K
  if (technicals.stoch_k != null) {
    signals.push(technicals.stoch_k < 20 ? 'buy' : technicals.stoch_k > 80 ? 'sell' : 'neutral');
  }

  // CCI
  if (technicals.cci != null) {
    signals.push(technicals.cci < -100 ? 'buy' : technicals.cci > 100 ? 'sell' : 'neutral');
  }

  const counts: SignalCount = {
    buy: signals.filter((s) => s === 'buy').length,
    sell: signals.filter((s) => s === 'sell').length,
    neutral: signals.filter((s) => s === 'neutral').length,
  };

  let verdict: TechVerdict = 'neutral';
  let label = '中性';
  if (counts.buy > counts.sell + counts.neutral) {
    verdict = 'bullish';
    label = '指标多数偏多';
  } else if (counts.sell > counts.buy + counts.neutral) {
    verdict = 'bearish';
    label = '指标多数偏空';
  }

  return {
    verdict,
    label: signals.length ? label === '中性' ? '指标分歧' : label : '数据不足',
    counts,
    trend: technicals.trend ?? '--',
    momentum: technicals.momentum ?? '--',
  };
}

// --- Component ---

export function TechnicalSummaryCard({ technicals }: TechnicalSummaryCardProps) {
  const summary = useMemo(() => computeSummary(technicals), [technicals]);
  const style = VERDICT_STYLES[summary.verdict];

  return (
    <div className="p-4 bg-fin-card rounded-lg border border-fin-border">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="text-sm font-semibold text-t-text">当前技术状态</div>
        <DashboardSourceBadge metaKey="technicals" />
      </div>

      <div className="flex flex-wrap items-center gap-4 mb-3">
        <div className={`px-3 py-2 rounded-md text-base font-semibold ${style.bg} ${style.text}`}>
          {summary.label}
        </div>
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-3 text-2xs">
            <span className="text-fin-success">偏多 {summary.counts.buy}</span>
            <span className="text-fin-danger">偏空 {summary.counts.sell}</span>
            <span className="text-fin-warning">中性: {summary.counts.neutral}</span>
          </div>
          <div className="text-2xs text-fin-muted">
            共 {summary.counts.buy + summary.counts.sell + summary.counts.neutral} 项技术指标
          </div>
        </div>
      </div>

      <p className="mb-4 text-sm leading-6 text-t-text2">日线均线与动量指标的当前状态统计，不是未来涨跌预测。</p>
      <div className="grid grid-cols-2 gap-3">
        <div className="flex flex-col">
          <span className="text-2xs text-fin-muted">趋势</span>
          <span className="text-sm text-fin-text font-medium mt-0.5">{TREND_LABELS[summary.trend] || summary.trend}</span>
        </div>
        <div className="flex flex-col">
          <span className="text-2xs text-fin-muted">动量</span>
          <span className="text-sm text-fin-text font-medium mt-0.5">{MOMENTUM_LABELS[summary.momentum] || summary.momentum}</span>
        </div>
      </div>
      {typeof technicals?.rsi === 'number' && technicals.rsi > 70 && <p className="mt-3 text-sm leading-6 text-t-warning">RSI {technicals.rsi.toFixed(1)} 处于超买区：上行趋势仍可能伴随短线回落风险。</p>}
      <details className="mt-4 border-t border-t-divider pt-3 text-xs text-t-text3">
        <summary className="cursor-pointer py-1 text-t-text2">指标口径</summary>
        <p className="mt-2 leading-6">MA5–MA200、EMA12/26、RSI、MACD、随机指标与 CCI 等权计数；偏多或偏空票数超过其余票数之和时标记多数。</p>
      </details>
    </div>
  );
}

export default TechnicalSummaryCard;
