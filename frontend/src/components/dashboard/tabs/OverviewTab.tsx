/**
 * OverviewTab - Container component for the overview dashboard panel.
 *
 * Renders overview sub-components in a responsive 2-3 column grid layout.
 * First row:  ScoreRing + AnalystRatingCard + DimensionRadar
 * Second row: KeyInsightsCard + RiskMetricsCard + HighlightsCard
 */
import { useDashboardStore } from '../../../store/dashboardStore';
import { useLatestReport } from '../../../hooks/useLatestReport';
import { ScoreRing } from './overview/ScoreRing';
import { AnalystRatingCard } from './overview/AnalystRatingCard';
import { DimensionRadar } from './overview/DimensionRadar';
import { KeyInsightsCard } from './overview/KeyInsightsCard';
import { RiskMetricsCard } from './overview/RiskMetricsCard';
import { HighlightsCard } from './overview/HighlightsCard';

// --- Component ---

export function OverviewTab() {
  const dashboardData = useDashboardStore((s) => s.dashboardData);
  const activeAsset = useDashboardStore((s) => s.activeAsset);
  const { data: reportData } = useLatestReport(activeAsset?.symbol);

  const valuation = dashboardData?.valuation;
  const technicals = dashboardData?.technicals;
  const news = dashboardData?.news?.market;

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {/* Row 1 */}
      <ScoreRing valuation={valuation} technicals={technicals} reportData={reportData} />
      <AnalystRatingCard technicals={technicals} reportData={reportData} />
      <DimensionRadar valuation={valuation} technicals={technicals} news={news} reportData={reportData} />

      {/* Row 2 */}
      <KeyInsightsCard valuation={valuation} technicals={technicals} news={news} reportData={reportData} />
      <RiskMetricsCard valuation={valuation} reportData={reportData} />
      <HighlightsCard valuation={valuation} technicals={technicals} reportData={reportData} />
    </div>
  );
}

export default OverviewTab;
