/**
 * OverviewTab - Container component for the overview dashboard panel.
 *
 * Renders overview sub-components in a responsive 2-3 column grid layout.
 * First row:  ScoreRing + AnalystRatingCard + DimensionRadar
 * Second row: FearGreedGauge + AgentStatusOverview + RiskMetricsCard
 * Third row:  KeyInsightsCard + HighlightsCard
 * Optional:   AiInsightCard when AI insights are available
 */
import { useDashboardStore } from '../../../store/dashboardStore';
import { useLatestReport } from '../../../hooks/useLatestReport';
import { ScoreRing } from './overview/ScoreRing';
import { AnalystRatingCard } from './overview/AnalystRatingCard';
import { DimensionRadar } from './overview/DimensionRadar';
import { KeyInsightsCard } from './overview/KeyInsightsCard';
import { RiskMetricsCard } from './overview/RiskMetricsCard';
import { HighlightsCard } from './overview/HighlightsCard';
import { FearGreedGauge } from './overview/FearGreedGauge';
import { AgentStatusOverview } from './overview/AgentStatusOverview';
import { AiInsightCard } from './shared/AiInsightCard';

// --- Component ---

export function OverviewTab() {
  const dashboardData = useDashboardStore((s) => s.dashboardData);
  const activeAsset = useDashboardStore((s) => s.activeAsset);
  const insightsData = useDashboardStore((s) => s.insightsData);
  const insightsLoading = useDashboardStore((s) => s.insightsLoading);
  const insightsError = useDashboardStore((s) => s.insightsError);
  const insightsStale = useDashboardStore((s) => s.insightsStale);

  const { data: reportData } = useLatestReport(activeAsset?.symbol, {
    sourceType: 'dashboard',
    fallbackToAnySource: false,
    preferredSourceTrigger: 'dashboard_deep_search',
  });

  const valuation = dashboardData?.valuation;
  const technicals = dashboardData?.technicals;
  const news = dashboardData?.news?.market;
  const overviewInsight = insightsData?.overview ?? null;

  return (
    <div className="space-y-4">
      {/* AI Overview Card (full width) */}
      <AiInsightCard
        tab="overview"
        insight={overviewInsight}
        loading={insightsLoading}
        error={insightsError}
        stale={insightsStale}
      />

      {/* Original grid layout */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {/* Row 1 */}
        <ScoreRing valuation={valuation} technicals={technicals} reportData={reportData} insightScore={overviewInsight?.score} />
        <AnalystRatingCard technicals={technicals} reportData={reportData} />
        <DimensionRadar valuation={valuation} technicals={technicals} news={news} reportData={reportData} />

        {/* Row 2 */}
        <FearGreedGauge reportData={reportData} />
        <AgentStatusOverview reportData={reportData} />
        <RiskMetricsCard valuation={valuation} reportData={reportData} />

        {/* Row 3 */}
        <KeyInsightsCard valuation={valuation} technicals={technicals} news={news} reportData={reportData} insightPoints={overviewInsight?.key_points} />
        <HighlightsCard valuation={valuation} technicals={technicals} reportData={reportData} />
      </div>
    </div>
  );
}

export default OverviewTab;
