import { useMemo } from 'react';

import type { NewsItem, TechnicalData, ValuationData } from '../../../../types/dashboard';
import type { LatestReportData } from '../../../../hooks/useLatestReport';
import { CardInfoTip } from '../../../ui/CardInfoTip';

interface DimensionRadarProps {
  valuation?: ValuationData | null;
  technicals?: TechnicalData | null;
  news?: NewsItem[];
  reportData?: LatestReportData | null;
}

interface Dimension {
  name: string;
  value: number;
}

const clampPercent = (value: number): number => Math.max(0, Math.min(100, Math.round(value)));

const readAgentConfidence = (
  reportData: LatestReportData | null | undefined,
  candidates: string[],
): number | null => {
  const report = reportData?.report as Record<string, unknown> | undefined;
  const agentStatus = report?.agent_status as Record<string, any> | undefined;
  if (!agentStatus || typeof agentStatus !== 'object') return null;

  for (const key of candidates) {
    const node = agentStatus[key];
    if (!node || typeof node !== 'object') continue;
    const confidenceRaw = node.confidence ?? node.score;
    const confidence = Number(confidenceRaw);
    if (!Number.isFinite(confidence)) continue;

    if (confidence <= 1) return clampPercent(confidence * 100);
    return clampPercent(confidence);
  }

  return null;
};

function computeDimensions(
  valuation: ValuationData | null | undefined,
  technicals: TechnicalData | null | undefined,
  news: NewsItem[] | undefined,
  reportData: LatestReportData | null | undefined,
): Dimension[] {
  let fundamentals = 0;
  if (valuation) {
    const fields = [
      valuation.trailing_pe,
      valuation.forward_pe,
      valuation.price_to_book,
      valuation.ev_to_ebitda,
      valuation.dividend_yield,
      valuation.market_cap,
    ];
    const filled = fields.filter((field) => field != null).length;
    fundamentals = clampPercent((filled / fields.length) * 100);
  }

  let technical = 0;
  if (technicals) {
    const fields = [
      technicals.rsi,
      technicals.macd,
      technicals.ma50,
      technicals.ma200,
      technicals.ema12,
      technicals.adx,
      technicals.cci,
    ];
    const filled = fields.filter((field) => field != null).length;
    technical = clampPercent((filled / fields.length) * 100);
  }

  const newsList = news ?? [];
  const newsCountScore = Math.min(100, newsList.length * 10);
  const relevanceList = newsList
    .map((item) => item.asset_relevance)
    .filter((value): value is number => typeof value === 'number' && Number.isFinite(value));
  const relevanceAvg = relevanceList.length
    ? relevanceList.reduce((sum, value) => sum + value, 0) / relevanceList.length
    : null;
  const newsSentiment = relevanceAvg == null
    ? newsCountScore
    : clampPercent(newsCountScore * (0.6 + 0.4 * relevanceAvg));

  const deepResearch = readAgentConfidence(reportData, ['deep_search_agent', 'deep_research_agent']) ?? 0;
  const macro = readAgentConfidence(reportData, ['macro_agent']) ?? 0;

  return [
    { name: '基本面', value: fundamentals },
    { name: '技术面', value: technical },
    { name: '新闻情绪', value: newsSentiment },
    { name: '深度研究', value: deepResearch },
    { name: '宏观环境', value: macro },
  ];
}

export function DimensionRadar({ valuation, technicals, news, reportData }: DimensionRadarProps) {
  const dimensions = useMemo(
    () => computeDimensions(valuation, technicals, news, reportData),
    [valuation, technicals, news, reportData],
  );

  return (
    <div className="flex flex-col p-4 bg-fin-card rounded-xl border border-fin-border">
      <div className="flex items-center gap-1 text-xs font-medium text-fin-muted mb-3">
        分析维度覆盖
        <CardInfoTip content="五维评估：技术面 / 基本面 / 新闻舆情 / 宏观 / 深度研究" />
      </div>

      <div className="space-y-2.5">
        {dimensions.map((item) => (
          <div key={item.name} className="flex items-center gap-2">
            <span className="text-2xs text-fin-muted w-16 shrink-0 text-right">{item.name}</span>
            <div className="flex-1 h-2 bg-fin-border rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-500 ${
                  item.value >= 70
                    ? 'bg-fin-success'
                    : item.value >= 40
                      ? 'bg-fin-warning'
                      : item.value > 0
                        ? 'bg-fin-danger'
                        : 'bg-fin-border'
                }`}
                style={{ width: `${item.value}%` }}
              />
            </div>
            <span className="text-2xs text-fin-text-secondary tabular-nums w-8">{item.value}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default DimensionRadar;
