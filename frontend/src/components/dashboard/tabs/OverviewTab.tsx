/**
 * OverviewTab - Container component for the overview dashboard panel.
 *
 * Layout strategy:
 * - Top: AI overview card (full width)
 * - Bottom: 3-column stacked layout (masonry-like) to avoid row-height whitespace
 */
import { useDashboardStore } from '../../../store/dashboardStore';
import { useLatestReport } from '../../../hooks/useLatestReport';
import type { SelectionItem, TechnicalData } from '../../../types/dashboard';
import { ScoreRing } from './overview/ScoreRing';
import { AnalystRatingCard } from './overview/AnalystRatingCard';
import { DimensionRadar } from './overview/DimensionRadar';
import { KeyInsightsCard } from './overview/KeyInsightsCard';
import { RiskMetricsCard } from './overview/RiskMetricsCard';
import { HighlightsCard } from './overview/HighlightsCard';
import { FearGreedGauge } from './overview/FearGreedGauge';
import { AgentStatusOverview } from './overview/AgentStatusOverview';
import { AiInsightCard } from './shared/AiInsightCard';
import { AnalystTargetCard } from './financial/AnalystTargetCard';
import { asRecord } from '../../../utils/record';

interface ActionSuggestion {
  action: string;
  rationale: string;
  entryRange: string | null;
  takeProfit: string | null;
  stopLoss: string | null;
}

function normalizeRecommendationText(reportData: ReturnType<typeof useLatestReport>['data']): string {
  const report = asRecord(reportData?.report);
  return String(report?.recommendation ?? report?.sentiment ?? '').trim().toLowerCase();
}

function getRecommendationAction(reportData: ReturnType<typeof useLatestReport>['data'], score: number | null | undefined): string {
  const recText = normalizeRecommendationText(reportData);
  if (/(strong\s*)?buy|bull|positive|增持|买入|强烈买入/.test(recText)) return '买入';
  if (/(strong\s*)?sell|bear|negative|减持|卖出|强烈卖出/.test(recText)) return '卖出';
  if (/hold|neutral|中性|持有|观望/.test(recText)) return '持有';

  if (score == null || !Number.isFinite(score)) return '持有';
  if (score >= 8) return '强烈买入';
  if (score >= 6) return '买入';
  if (score >= 4) return '持有';
  if (score >= 3) return '观望';
  return '减仓';
}

function pickSupportResistance(technicals?: TechnicalData | null, currentPrice?: number | null): {
  entryRange: string | null;
  takeProfit: string | null;
  stopLoss: string | null;
} {
  const support = [...(technicals?.support_levels ?? [])]
    .filter((level): level is number => Number.isFinite(level))
    .sort((left, right) => left - right);
  const resistance = [...(technicals?.resistance_levels ?? [])]
    .filter((level): level is number => Number.isFinite(level))
    .sort((left, right) => left - right);

  const upperSupport = support.filter((level) => currentPrice == null || level <= currentPrice).slice(-2);
  const entryCandidate = upperSupport.length >= 2 ? upperSupport : support.slice(0, 2);
  const entryRange = entryCandidate.length === 2
    ? `$${entryCandidate[0].toFixed(2)} - $${entryCandidate[1].toFixed(2)}`
    : entryCandidate.length === 1
      ? `$${entryCandidate[0].toFixed(2)}`
      : null;

  const nextResistance = resistance.find((level) => currentPrice == null || level >= currentPrice) ?? resistance.at(-1);
  const takeProfit = nextResistance != null ? `$${nextResistance.toFixed(2)}` : null;

  const stopBase = entryCandidate[0] ?? null;
  const stopLoss = stopBase != null ? `$${(stopBase * 0.97).toFixed(2)}` : null;
  return { entryRange, takeProfit, stopLoss };
}

function buildActionSuggestion(
  reportData: ReturnType<typeof useLatestReport>['data'],
  score: number | null | undefined,
  technicals?: TechnicalData | null,
): ActionSuggestion {
  const action = getRecommendationAction(reportData, score);
  const currentPrice = technicals?.close ?? null;
  const { entryRange, takeProfit, stopLoss } = pickSupportResistance(technicals, currentPrice);

  const rationale = action === '强烈买入' || action === '买入'
    ? '当前评分偏多，建议分批布局并控制仓位。'
    : action === '卖出' || action === '减仓'
      ? '当前信号偏弱，优先控制回撤风险。'
      : score == null || !Number.isFinite(score)
        ? '运行综合分析后可获得更准确的建议。'
        : '当前信号分歧较大，建议持有观望等待确认。';

  return { action, rationale, entryRange, takeProfit, stopLoss };
}

// --- Component ---

export function OverviewTab() {
  const dashboardData = useDashboardStore((s) => s.dashboardData);
  const activeAsset = useDashboardStore((s) => s.activeAsset);
  const insightsData = useDashboardStore((s) => s.insightsData);
  const insightsLoading = useDashboardStore((s) => s.insightsLoading);
  const insightsError = useDashboardStore((s) => s.insightsError);
  const insightsStale = useDashboardStore((s) => s.insightsStale);
  const setActiveSelection = useDashboardStore((s) => s.setActiveSelection);

  const handleAskAbout = (selection: SelectionItem) => {
    setActiveSelection(selection);
  };

  const { data: reportData } = useLatestReport(activeAsset?.symbol, {
    sourceType: 'dashboard',
    fallbackToAnySource: false,
    preferredSourceTrigger: 'dashboard_deep_search',
  });

  const valuation = dashboardData?.valuation;
  const technicals = dashboardData?.technicals;
  const news = dashboardData?.news?.market;
  const analystTargets = dashboardData?.analyst_targets;
  const recommendations = dashboardData?.recommendations;
  const overviewInsight = insightsData?.overview ?? null;
  const actionSuggestion = buildActionSuggestion(reportData, overviewInsight?.score, technicals);

  return (
    <div className="space-y-4">
      {/* AI Overview Card (full width) */}
      <AiInsightCard
        tab="overview"
        insight={overviewInsight}
        loading={insightsLoading}
        error={insightsError}
        stale={insightsStale}
        actionSuggestion={actionSuggestion}
        onAskAbout={handleAskAbout}
      />

      {/* Unified stacked columns (reduce empty white blocks caused by row-based grid) */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 items-start">
        <div className="space-y-4">
          <ScoreRing valuation={valuation} technicals={technicals} reportData={reportData} insightScore={overviewInsight?.score} />
          <FearGreedGauge reportData={reportData} macroSnapshot={dashboardData?.macro_snapshot} />
          <KeyInsightsCard valuation={valuation} technicals={technicals} news={news} reportData={reportData} insightPoints={overviewInsight?.key_points} />
        </div>

        <div className="space-y-4">
          <AnalystRatingCard technicals={technicals} reportData={reportData} />
          <AgentStatusOverview reportData={reportData} />
          <HighlightsCard valuation={valuation} technicals={technicals} reportData={reportData} />
        </div>

        <div className="space-y-4">
          <DimensionRadar valuation={valuation} technicals={technicals} news={news} reportData={reportData} />
          <RiskMetricsCard valuation={valuation} reportData={reportData} />
          <AnalystTargetCard
            targets={analystTargets}
            recommendations={recommendations}
            currentPrice={technicals?.close ?? null}
          />
        </div>
      </div>
    </div>
  );
}

export default OverviewTab;
