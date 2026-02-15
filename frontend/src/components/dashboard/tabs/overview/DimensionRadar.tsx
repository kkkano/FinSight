/**
 * DimensionRadar - 5-dimension analysis coverage display.
 *
 * Dimensions: Fundamentals / Technicals / News Sentiment / Deep Research / Macro
 * Without report: Fundamentals + Technicals + News have values, others show 0.
 * With report: all 5 filled from agent status.
 *
 * Uses a table-based bar chart representation (no ECharts dependency).
 */
import { useMemo } from 'react';

import type { ValuationData, TechnicalData, NewsItem } from '../../../../types/dashboard';
import type { LatestReportData } from '../../../../hooks/useLatestReport';

// --- Props ---

interface DimensionRadarProps {
  valuation?: ValuationData | null;
  technicals?: TechnicalData | null;
  news?: NewsItem[];
  reportData?: LatestReportData | null;
}

// --- Types ---

interface Dimension {
  name: string;
  value: number; // 0-100
}

// --- Helpers ---

function computeDimensions(
  valuation: ValuationData | null | undefined,
  technicals: TechnicalData | null | undefined,
  news: NewsItem[] | undefined,
  reportData: LatestReportData | null | undefined,
): Dimension[] {
  const hasReport = !!reportData?.report;

  // Fundamentals: based on valuation data completeness
  let fundamentals = 0;
  if (valuation) {
    const fields = [
      valuation.trailing_pe, valuation.forward_pe, valuation.price_to_book,
      valuation.ev_to_ebitda, valuation.dividend_yield, valuation.market_cap,
    ];
    const filled = fields.filter((f) => f != null).length;
    fundamentals = Math.round((filled / fields.length) * 100);
  }

  // Technicals: based on data completeness
  let techScore = 0;
  if (technicals) {
    const fields = [
      technicals.rsi, technicals.macd, technicals.ma50, technicals.ma200,
      technicals.ema12, technicals.adx, technicals.cci,
    ];
    const filled = fields.filter((f) => f != null).length;
    techScore = Math.round((filled / fields.length) * 100);
  }

  // News sentiment: based on news count
  const newsCount = news?.length ?? 0;
  const newsScore = newsCount > 0 ? Math.min(100, newsCount * 10) : 0;

  // Deep research: only from report
  let researchScore = 0;
  if (hasReport) {
    const report = reportData!.report as Record<string, unknown>;
    researchScore = report.core_viewpoints ? 85 : 60;
  }

  // Macro: only from report
  const macroScore = hasReport ? 70 : 0;

  return [
    { name: '基本面', value: fundamentals },
    { name: '技术面', value: techScore },
    { name: '新闻舆情', value: newsScore },
    { name: '深度研究', value: researchScore },
    { name: '宏观环境', value: macroScore },
  ];
}

// --- Component ---

export function DimensionRadar({ valuation, technicals, news, reportData }: DimensionRadarProps) {
  const dimensions = useMemo(
    () => computeDimensions(valuation, technicals, news, reportData),
    [valuation, technicals, news, reportData],
  );

  return (
    <div className="flex flex-col p-4 bg-fin-card rounded-xl border border-fin-border">
      <div className="text-xs font-medium text-fin-muted mb-3">
        分析维度覆盖
      </div>

      <div className="space-y-2.5">
        {dimensions.map((d) => (
          <div key={d.name} className="flex items-center gap-2">
            <span className="text-2xs text-fin-muted w-16 shrink-0 text-right">
              {d.name}
            </span>
            <div className="flex-1 h-2 bg-fin-border rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-500 ${
                  d.value >= 70
                    ? 'bg-fin-success'
                    : d.value >= 40
                      ? 'bg-fin-warning'
                      : d.value > 0
                        ? 'bg-fin-danger'
                        : 'bg-fin-border'
                }`}
                style={{ width: `${d.value}%` }}
              />
            </div>
            <span className="text-2xs text-fin-text-secondary tabular-nums w-8">
              {d.value}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default DimensionRadar;
