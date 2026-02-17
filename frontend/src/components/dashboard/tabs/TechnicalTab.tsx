/**
 * TechnicalTab - Container component for the technical dashboard panel.
 *
 * Renders technical analysis sub-components:
 * AI Insight Card (full width, when available)
 * Row 1: TechnicalSummaryCard (full width)
 * Row 2: MovingAverageTable + OscillatorTable
 * Row 3: SupportResistanceChart + BollingerVolumeCard
 */
import { useDashboardStore } from '../../../store/dashboardStore';
import { TechnicalSummaryCard } from './technical/TechnicalSummaryCard';
import { MovingAverageTable } from './technical/MovingAverageTable';
import { OscillatorTable } from './technical/OscillatorTable';
import { SupportResistanceChart } from './technical/SupportResistanceChart';
import { BollingerVolumeCard } from './technical/BollingerVolumeCard';
import { AiInsightCard } from './shared/AiInsightCard';

// --- Component ---

export function TechnicalTab() {
  const dashboardData = useDashboardStore((s) => s.dashboardData);
  const insightsData = useDashboardStore((s) => s.insightsData);
  const insightsLoading = useDashboardStore((s) => s.insightsLoading);
  const insightsError = useDashboardStore((s) => s.insightsError);
  const insightsStale = useDashboardStore((s) => s.insightsStale);

  const technicals = dashboardData?.technicals;
  const technicalInsight = insightsData?.technical ?? null;

  return (
    <div className="flex flex-col gap-4">
      {/* AI Technical Analysis Card */}
      <AiInsightCard
        tab="technical"
        insight={technicalInsight}
        loading={insightsLoading}
        error={insightsError}
        stale={insightsStale}
      />

      {/* Row 1: Summary full width */}
      <TechnicalSummaryCard technicals={technicals} />

      {/* Row 2: MA + Oscillators side by side */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <MovingAverageTable technicals={technicals} />
        <OscillatorTable technicals={technicals} />
      </div>

      {/* Row 3: Support/Resistance + Bollinger/Volume */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <SupportResistanceChart technicals={technicals} />
        <BollingerVolumeCard technicals={technicals} />
      </div>
    </div>
  );
}

export default TechnicalTab;
