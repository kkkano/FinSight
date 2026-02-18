import { useMemo } from 'react';

import type { LatestReportData } from '../../../../hooks/useLatestReport';
import type { ValuationData } from '../../../../types/dashboard';

type RiskLevel = 'low' | 'medium' | 'high';

interface RiskMetricsCardProps {
  valuation?: ValuationData | null;
  reportData?: LatestReportData | null;
}

interface RiskItem {
  label: string;
  level: RiskLevel;
}

const RISK_STYLES: Record<RiskLevel, { dot: string; text: string; badge: string; label: string }> = {
  low: {
    dot: 'bg-fin-success',
    text: 'text-fin-success',
    badge: 'bg-fin-success/10',
    label: '低',
  },
  medium: {
    dot: 'bg-fin-warning',
    text: 'text-fin-warning',
    badge: 'bg-fin-warning/10',
    label: '中',
  },
  high: {
    dot: 'bg-fin-danger',
    text: 'text-fin-danger',
    badge: 'bg-fin-danger/10',
    label: '高',
  },
};

const asRecord = (value: unknown): Record<string, unknown> | null => (
  value && typeof value === 'object' ? (value as Record<string, unknown>) : null
);

function computeBaselineRisks(valuation: ValuationData | null | undefined): RiskItem[] {
  const risks: RiskItem[] = [];

  const beta = valuation?.beta;
  if (beta != null) {
    const level: RiskLevel = beta > 1.5 ? 'high' : beta > 1.0 ? 'medium' : 'low';
    risks.push({ label: `Beta 波动（${beta.toFixed(2)}）`, level });
  }

  const high = valuation?.week52_high;
  const low = valuation?.week52_low;
  if (high != null && low != null && high > 0) {
    const range = ((high - low) / high) * 100;
    const level: RiskLevel = range > 60 ? 'high' : range > 30 ? 'medium' : 'low';
    risks.push({ label: `52 周振幅（${range.toFixed(0)}%）`, level });
  }

  const pe = valuation?.trailing_pe;
  if (pe != null) {
    const level: RiskLevel = pe > 40 ? 'high' : pe > 20 ? 'medium' : 'low';
    risks.push({ label: `估值压力（PE ${pe.toFixed(1)}）`, level });
  }

  if (risks.length === 0) {
    risks.push({ label: '暂无可计算风险指标', level: 'medium' });
  }
  return risks;
}

function extractReportRisks(reportData: LatestReportData | null | undefined): RiskItem[] {
  const report = asRecord(reportData?.report);
  if (!report) return [];

  const rawRisks = report.risks ?? report.risk_factors;
  if (!Array.isArray(rawRisks)) return [];

  return rawRisks
    .slice(0, 4)
    .map((item): RiskItem | null => {
      if (typeof item === 'string') {
        const text = item.trim();
        if (!text) return null;
        return { label: text, level: 'medium' };
      }
      const node = asRecord(item);
      if (!node) return null;
      const label = String(node.title ?? node.description ?? node.text ?? '').trim();
      if (!label) return null;
      const severity = String(node.severity ?? node.level ?? 'medium').toLowerCase();
      const level: RiskLevel = severity.includes('high') || severity.includes('critical')
        ? 'high'
        : severity.includes('low')
          ? 'low'
          : 'medium';
      return { label, level };
    })
    .filter((item): item is RiskItem => Boolean(item));
}

function readRiskAgentStatus(reportData: LatestReportData | null | undefined): string {
  const report = asRecord(reportData?.report);
  const node = asRecord(asRecord(report?.agent_status)?.risk_agent);
  const raw = String(node?.status || '').trim().toLowerCase();
  if (!raw || raw === 'not_run') return '未运行';
  if (raw === 'success') return '完成';
  if (raw === 'fallback') return '降级';
  if (raw === 'error') return '失败';
  return '未知';
}

export function RiskMetricsCard({ valuation, reportData }: RiskMetricsCardProps) {
  const riskAgentStatus = useMemo(() => readRiskAgentStatus(reportData), [reportData]);

  const risks = useMemo(() => {
    const reportRisks = extractReportRisks(reportData);
    if (reportRisks.length > 0) return reportRisks;
    return computeBaselineRisks(valuation);
  }, [valuation, reportData]);

  const overallLevel = useMemo(() => {
    const highCount = risks.filter((item) => item.level === 'high').length;
    const mediumCount = risks.filter((item) => item.level === 'medium').length;
    if (highCount >= 2) return 'high' as RiskLevel;
    if (highCount >= 1 || mediumCount >= 2) return 'medium' as RiskLevel;
    return 'low' as RiskLevel;
  }, [risks]);

  const overallStyle = RISK_STYLES[overallLevel];

  return (
    <div className="flex flex-col p-4 bg-fin-card rounded-xl border border-fin-border">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-medium text-fin-muted">风险概览</span>
        <span className={`text-2xs font-semibold px-2 py-0.5 rounded ${overallStyle.text} ${overallStyle.badge}`}>
          整体风险：{overallStyle.label}
        </span>
      </div>

      <div className="text-2xs text-fin-muted mb-3">
        Risk Agent：<span className="text-fin-text">{riskAgentStatus}</span>
      </div>

      <div className="space-y-2">
        {risks.map((risk, idx) => {
          const style = RISK_STYLES[risk.level];
          return (
            <div key={`${risk.label}-${idx}`} className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full shrink-0 ${style.dot}`} />
              <span className="text-sm text-fin-text flex-1 truncate">{risk.label}</span>
              <span className={`text-2xs ${style.text}`}>{style.label}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default RiskMetricsCard;
