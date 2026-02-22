/**
 * TechnicalTab - Container component for the technical dashboard panel.
 *
 * Renders technical analysis sub-components:
 * AI Insight Card (full width, when available)
 * Row 1: K-line chart with support/resistance (full width)
 * Row 2: TechnicalSummaryCard (full width)
 * Row 3: MovingAverageTable + OscillatorTable
 * Row 4: RSI + MACD sub-charts (G2 new)
 * Row 5: BollingerVolumeCard
 */
import { useDashboardStore } from '../../../store/dashboardStore';
import { TechnicalSummaryCard } from './technical/TechnicalSummaryCard';
import { MovingAverageTable } from './technical/MovingAverageTable';
import { OscillatorTable } from './technical/OscillatorTable';
import { SupportResistanceChart } from './technical/SupportResistanceChart';
import { BollingerVolumeCard } from './technical/BollingerVolumeCard';
import { TechnicalSubCharts } from './technical/TechnicalSubCharts';
import { AiInsightCard } from './shared/AiInsightCard';
import type { SelectionItem } from '../../../types/dashboard';

// --- Component ---

export function TechnicalTab() {
  const dashboardData = useDashboardStore((s) => s.dashboardData);
  const insightsData = useDashboardStore((s) => s.insightsData);
  const insightsLoading = useDashboardStore((s) => s.insightsLoading);
  const insightsError = useDashboardStore((s) => s.insightsError);
  const insightsStale = useDashboardStore((s) => s.insightsStale);
  const setActiveSelection = useDashboardStore((s) => s.setActiveSelection);

  const handleAskAbout = (selection: SelectionItem) => {
    setActiveSelection(selection);
  };

  const technicals = dashboardData?.technicals;
  const technicalsFallbackReason = dashboardData?.technicals_fallback_reason;
  const marketChart = dashboardData?.charts?.market_chart;
  const indicatorSeries = dashboardData?.indicator_series;
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
        onAskAbout={handleAskAbout}
      />

      {/* K-line chart with support/resistance — full width */}
      {!technicals && technicalsFallbackReason && (
        <div className="rounded-xl border border-amber-500/40 bg-amber-500/10 px-4 py-3">
          <div className="text-xs font-semibold text-amber-200">技术面数据暂不可用</div>
          <div className="mt-1 text-2xs text-amber-100/90">原因：{technicalsFallbackReason}</div>
          <div className="mt-1 text-2xs text-amber-100/80">
            建议：稍后重试，或切换流动性更高的标的以验证是否为数据源瞬时抖动。
          </div>
        </div>
      )}

      <SupportResistanceChart technicals={technicals} marketChart={marketChart} />

      {/* Row 2: Summary full width */}
      <TechnicalSummaryCard technicals={technicals} />

      {/* Row 3: MA + Oscillators side by side */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <MovingAverageTable technicals={technicals} />
        <OscillatorTable technicals={technicals} />
      </div>

      {/* Row 4: RSI + MACD time-series sub-charts (G2 new) */}
      <TechnicalSubCharts indicatorSeries={indicatorSeries} />

      {/* Row 5: Bollinger/Volume */}
      <BollingerVolumeCard technicals={technicals} />
    </div>
  );
}

export default TechnicalTab;
