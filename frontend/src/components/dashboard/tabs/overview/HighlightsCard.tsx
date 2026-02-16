import { useMemo } from 'react';

import type { TechnicalData, ValuationData } from '../../../../types/dashboard';
import type { LatestReportData } from '../../../../hooks/useLatestReport';

interface HighlightsCardProps {
  valuation?: ValuationData | null;
  technicals?: TechnicalData | null;
  reportData?: LatestReportData | null;
}

interface HighlightPair {
  bullish: string[];
  bearish: string[];
}

function generateAutoHighlights(
  valuation: ValuationData | null | undefined,
  technicals: TechnicalData | null | undefined,
): HighlightPair {
  const bullish: string[] = [];
  const bearish: string[] = [];

  const close = technicals?.close;
  const ma200 = technicals?.ma200;
  const ma50 = technicals?.ma50;

  if (close != null && ma200 != null) {
    if (close > ma200) bullish.push('股价高于 MA200');
    else bearish.push('股价低于 MA200');
  }

  if (close != null && ma50 != null) {
    if (close > ma50) bullish.push('股价高于 MA50');
    else bearish.push('股价低于 MA50');
  }

  const rsi = technicals?.rsi;
  if (rsi != null) {
    if (rsi >= 70) {
      bearish.push('RSI 进入超买');
    } else if (rsi <= 30) {
      bullish.push('RSI 进入超卖区，存在反弹窗口');
    } else {
      bullish.push('RSI 处于中性区间');
    }
  }

  const macdHist = technicals?.macd_hist;
  if (macdHist != null) {
    if (macdHist > 0) bullish.push('MACD 金叉');
    else bearish.push('MACD 死叉');
  }

  const pe = valuation?.trailing_pe;
  if (pe != null) {
    if (pe < 20) bullish.push('估值处于相对低位');
    else if (pe > 35) bearish.push('估值偏高');
  }

  const beta = valuation?.beta;
  if (beta != null) {
    if (beta < 1.0) bullish.push('Beta 偏低，波动较可控');
    else if (beta > 1.5) bearish.push('Beta 偏高，波动风险较大');
  }

  return {
    bullish: bullish.slice(0, 4),
    bearish: bearish.slice(0, 4),
  };
}

function extractReportHighlights(reportData: LatestReportData | null | undefined): HighlightPair | null {
  if (!reportData?.report) return null;
  const report = reportData.report as Record<string, unknown>;
  const viewpoints = report.core_viewpoints;
  if (!Array.isArray(viewpoints)) return null;

  const bullish: string[] = [];
  const bearish: string[] = [];

  for (const item of viewpoints) {
    if (!item || typeof item !== 'object') continue;
    const row = item as Record<string, unknown>;
    const category = String(row.category ?? row.sentiment ?? '').toLowerCase();
    const text = String(row.title ?? row.content ?? row.text ?? '');
    if (!text) continue;

    if (category.includes('bull') || category.includes('positive') || category.includes('strength')) {
      bullish.push(text);
    } else if (
      category.includes('bear') ||
      category.includes('negative') ||
      category.includes('risk') ||
      category.includes('weakness')
    ) {
      bearish.push(text);
    }
  }

  if (!bullish.length && !bearish.length) return null;
  return { bullish: bullish.slice(0, 4), bearish: bearish.slice(0, 4) };
}

export function HighlightsCard({ valuation, technicals, reportData }: HighlightsCardProps) {
  const highlights = useMemo(() => {
    const reportHighlights = extractReportHighlights(reportData);
    if (reportHighlights) return reportHighlights;
    return generateAutoHighlights(valuation, technicals);
  }, [valuation, technicals, reportData]);

  return (
    <div className="flex flex-col p-4 bg-fin-card rounded-xl border border-fin-border">
      <div className="text-xs font-medium text-fin-muted mb-3">多空亮点</div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <div className="text-2xs font-semibold text-fin-success mb-2">看多因素</div>
          {highlights.bullish.length === 0 ? (
            <div className="text-2xs text-fin-muted">--</div>
          ) : (
            <ul className="space-y-1.5">
              {highlights.bullish.map((item, idx) => (
                <li key={idx} className="flex items-start gap-1.5 text-2xs text-fin-text">
                  <span className="text-fin-success mt-0.5 shrink-0">+</span>
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div>
          <div className="text-2xs font-semibold text-fin-danger mb-2">看空因素</div>
          {highlights.bearish.length === 0 ? (
            <div className="text-2xs text-fin-muted">--</div>
          ) : (
            <ul className="space-y-1.5">
              {highlights.bearish.map((item, idx) => (
                <li key={idx} className="flex items-start gap-1.5 text-2xs text-fin-text">
                  <span className="text-fin-danger mt-0.5 shrink-0">-</span>
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

export default HighlightsCard;
