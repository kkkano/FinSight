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
import type { PredictionOverlay } from '../../../types/chartPrediction';

// --- Component ---

interface TechnicalTabProps {
  predictionOverlay?: PredictionOverlay | null;
}

export function TechnicalTab({ predictionOverlay }: TechnicalTabProps) {
  const dashboardData = useDashboardStore((s) => s.dashboardData);

  const technicals = dashboardData?.technicals;
  const technicalsFallbackReason = dashboardData?.technicals_fallback_reason;
  const marketChart = dashboardData?.charts?.market_chart;
  const indicatorSeries = dashboardData?.indicator_series;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2 border-y border-t-border py-2 text-2xs text-t-text3">
        <span>规则指标 · RSI、MACD、均线和支撑阻力均由服务端基于真实 K 线计算</span>
        <span className="rounded border border-t-accent/30 bg-t-accent/10 px-1.5 py-0.5 text-t-accent">RULES</span>
      </div>

      {/* K-line chart with support/resistance — full width */}
      {!technicals && technicalsFallbackReason && (
        <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3">
          <div className="text-xs font-semibold text-amber-200">技术面数据暂不可用</div>
          <div className="mt-1 text-2xs text-amber-100/90">原因：{technicalsFallbackReason}</div>
          <div className="mt-1 text-2xs text-amber-100/80">
            建议：稍后重试，或切换流动性更高的标的以验证是否为数据源瞬时抖动。
          </div>
        </div>
      )}

      <SupportResistanceChart
        technicals={technicals}
        marketChart={marketChart}
        marketAsOf={dashboardData?.meta?.market_chart?.as_of}
        predictionOverlay={predictionOverlay}
      />

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
