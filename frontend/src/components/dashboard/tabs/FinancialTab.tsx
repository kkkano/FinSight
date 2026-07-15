/**
 * FinancialTab - Container component for the financial dashboard panel.
 *
 * Renders financial sub-components:
 * AI Insight Card (full width, when available)
 * Row 1: IncomeTable (full width)
 * Row 2: ProfitabilityChart + ValuationGrid
 * Row 3: EarningsSurpriseChart + AnalystTargetCard  (G2 new)
 * Row 4: BalanceSheetSummary
 */
import { useDashboardStore } from '../../../store/dashboardStore';
import { IncomeTable } from './financial/IncomeTable';
import { ProfitabilityChart } from './financial/ProfitabilityChart';
import { ValuationGrid } from './financial/ValuationGrid';
import { BalanceSheetSummary } from './financial/BalanceSheetSummary';
import { EarningsSurpriseChart } from './financial/EarningsSurpriseChart';
import { AnalystTargetCard } from './financial/AnalystTargetCard';

// --- Component ---

export function FinancialTab() {
  const dashboardData = useDashboardStore((s) => s.dashboardData);

  const financials = dashboardData?.financials;
  const valuation = dashboardData?.valuation;
  const earningsHistory = dashboardData?.earnings_history;
  const analystTargets = dashboardData?.analyst_targets;
  const recommendations = dashboardData?.recommendations;
  const currentPrice = dashboardData?.technicals?.close ?? dashboardData?.snapshot?.index_level ?? null;

  return (
    <div className="flex flex-col gap-4">
      <div className="border-y border-t-border py-2 text-2xs text-t-text3">
        财务事实 · 来自结构化财报与行情供应商，不是 AI 评分
      </div>

      {/* Row 1: Income table full width */}
      <IncomeTable financials={financials} />

      {/* Row 2: Profitability + Valuation side by side */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ProfitabilityChart financials={financials} />
        <ValuationGrid valuation={valuation} />
      </div>

      {/* Row 3: EPS Surprise + Analyst Targets (G2 new) */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <EarningsSurpriseChart data={earningsHistory} />
        <AnalystTargetCard
          targets={analystTargets}
          recommendations={recommendations}
          currentPrice={currentPrice}
        />
      </div>

      {/* Row 4: Balance sheet summary */}
      <BalanceSheetSummary financials={financials} />
    </div>
  );
}

export default FinancialTab;
