/**
 * RiskMetricsCard - Risk metrics display.
 *
 * Shows Beta / volatility from valuation.
 * Without report: simple risk level (Low/Med/High) based on beta.
 * With report: top 4 risks with color indicators.
 */
import { useMemo } from 'react';

import type { ValuationData } from '../../../../types/dashboard';
import type { LatestReportData } from '../../../../hooks/useLatestReport';

// --- Props ---

interface RiskMetricsCardProps {
  valuation?: ValuationData | null;
  reportData?: LatestReportData | null;
}

// --- Types ---

type RiskLevel = 'low' | 'medium' | 'high';

interface RiskItem {
  label: string;
  level: RiskLevel;
}

// --- Helpers ---

const RISK_STYLES: Record<RiskLevel, { dot: string; text: string; label: string }> = {
  low: { dot: 'bg-fin-success', text: 'text-fin-success', label: '低' },
  medium: { dot: 'bg-fin-warning', text: 'text-fin-warning', label: '中' },
  high: { dot: 'bg-fin-danger', text: 'text-fin-danger', label: '高' },
};

function computeBaselineRisks(valuation: ValuationData | null | undefined): RiskItem[] {
  const risks: RiskItem[] = [];

  const beta = valuation?.beta;
  if (beta != null) {
    const level: RiskLevel = beta > 1.5 ? 'high' : beta > 1.0 ? 'medium' : 'low';
    risks.push({ label: `Beta 波动 (${beta.toFixed(2)})`, level });
  } else {
    risks.push({ label: 'Beta 波动', level: 'medium' });
  }

  // 52-week range risk
  const high = valuation?.week52_high;
  const low = valuation?.week52_low;
  if (high != null && low != null && high > 0) {
    const range = ((high - low) / high) * 100;
    const level: RiskLevel = range > 60 ? 'high' : range > 30 ? 'medium' : 'low';
    risks.push({ label: `52周波幅 (${range.toFixed(0)}%)`, level });
  }

  // PE valuation risk
  const pe = valuation?.trailing_pe;
  if (pe != null) {
    const level: RiskLevel = pe > 40 ? 'high' : pe > 20 ? 'medium' : 'low';
    risks.push({ label: `估值风险 (PE ${pe.toFixed(1)})`, level });
  }

  return risks;
}

function extractReportRisks(reportData: LatestReportData | null | undefined): RiskItem[] | null {
  if (!reportData?.report) return null;
  const report = reportData.report as Record<string, unknown>;
  const risks = report.risks ?? report.risk_factors;
  if (!Array.isArray(risks)) return null;

  return risks.slice(0, 4).map((r: unknown) => {
    if (typeof r === 'string') {
      return { label: r, level: 'medium' as RiskLevel };
    }
    if (typeof r === 'object' && r !== null) {
      const obj = r as Record<string, unknown>;
      const label = String(obj.title ?? obj.description ?? obj.text ?? '');
      const severity = String(obj.severity ?? obj.level ?? 'medium').toLowerCase();
      const level: RiskLevel = severity.includes('high') || severity.includes('critical')
        ? 'high'
        : severity.includes('low')
          ? 'low'
          : 'medium';
      return { label, level };
    }
    return { label: '--', level: 'medium' as RiskLevel };
  });
}

// --- Component ---

export function RiskMetricsCard({ valuation, reportData }: RiskMetricsCardProps) {
  const risks = useMemo(() => {
    const reportRisks = extractReportRisks(reportData);
    if (reportRisks && reportRisks.length > 0) return reportRisks;
    return computeBaselineRisks(valuation);
  }, [valuation, reportData]);

  // Overall risk level
  const overallLevel = useMemo(() => {
    const highCount = risks.filter((r) => r.level === 'high').length;
    const medCount = risks.filter((r) => r.level === 'medium').length;
    if (highCount >= 2) return 'high' as RiskLevel;
    if (highCount >= 1 || medCount >= 2) return 'medium' as RiskLevel;
    return 'low' as RiskLevel;
  }, [risks]);

  const overallStyle = RISK_STYLES[overallLevel];

  return (
    <div className="flex flex-col p-4 bg-fin-card rounded-xl border border-fin-border">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-medium text-fin-muted">风险指标</span>
        <span className={`text-2xs font-semibold px-2 py-0.5 rounded ${overallStyle.text} bg-opacity-10`}>
          整体风险: {overallStyle.label}
        </span>
      </div>

      {risks.length === 0 ? (
        <div className="text-sm text-fin-muted">--</div>
      ) : (
        <div className="space-y-2">
          {risks.map((risk, idx) => {
            const style = RISK_STYLES[risk.level];
            return (
              <div key={idx} className="flex items-center gap-2">
                <span className={`w-2 h-2 rounded-full shrink-0 ${style.dot}`} />
                <span className="text-sm text-fin-text flex-1 truncate">{risk.label}</span>
                <span className={`text-2xs ${style.text}`}>{style.label}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default RiskMetricsCard;
