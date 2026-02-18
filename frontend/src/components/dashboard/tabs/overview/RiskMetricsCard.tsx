import { useMemo } from 'react';

import type { LatestReportData } from '../../../../hooks/useLatestReport';
import type { ValuationData } from '../../../../types/dashboard';
import { CardInfoTip } from '../../../ui/CardInfoTip';
import { asRecord } from '../../../../utils/record';

type RiskLevel = 'low' | 'medium' | 'high';
type RiskItemKind = 'financial' | 'diagnostic';

interface RiskMetricsCardProps {
  valuation?: ValuationData | null;
  reportData?: LatestReportData | null;
}

interface RiskItem {
  label: string;
  level: RiskLevel;
  kind: RiskItemKind;
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

const EVIDENCE_QUALITY_KEYWORDS = [
  '质量门槛',
  '证据',
  '引用',
  'citation',
  '10-k',
  '10-q',
  '业绩电话会',
  '纪要',
  '路透',
  'reuters',
  'bloomberg',
  'wsj',
  'ft',
  'cnbc',
  'yahoo',
  '摘录',
];

const EXECUTION_DIAGNOSTIC_KEYWORDS = [
  'agent',
  'diagnostic',
  'orchestration',
  'policy',
  'analysis_depth',
  'conflict',
  '未运行',
  '未执行',
  '冲突',
  '裁决',
  '可信度受限',
  '调度',
];

const isOperationalDiagnosticText = (text: string): boolean => {
  const lower = text.toLowerCase();
  return [...EXECUTION_DIAGNOSTIC_KEYWORDS, ...EVIDENCE_QUALITY_KEYWORDS]
    .some((token) => lower.includes(token));
};

function computeBaselineRisks(valuation: ValuationData | null | undefined): RiskItem[] {
  const risks: RiskItem[] = [];

  const beta = valuation?.beta;
  if (beta != null) {
    const level: RiskLevel = beta > 1.5 ? 'high' : beta > 1.0 ? 'medium' : 'low';
    risks.push({ label: `Beta 波动（${beta.toFixed(2)}）`, level, kind: 'financial' });
  }

  const high = valuation?.week52_high;
  const low = valuation?.week52_low;
  if (high != null && low != null && high > 0) {
    const range = ((high - low) / high) * 100;
    const level: RiskLevel = range > 60 ? 'high' : range > 30 ? 'medium' : 'low';
    risks.push({ label: `52 周振幅（${range.toFixed(0)}%）`, level, kind: 'financial' });
  }

  const pe = valuation?.trailing_pe;
  if (pe != null) {
    const level: RiskLevel = pe > 40 ? 'high' : pe > 20 ? 'medium' : 'low';
    risks.push({ label: `估值压力（PE ${pe.toFixed(1)}）`, level, kind: 'financial' });
  }

  if (risks.length === 0) {
    risks.push({ label: '暂无可计算风险指标', level: 'medium', kind: 'financial' });
  }
  return risks;
}

function extractReportRisks(reportData: LatestReportData | null | undefined): RiskItem[] {
  const report = asRecord(reportData?.report);
  if (!report) return [];

  const rawRisks = report.risks ?? report.risk_factors;
  if (!Array.isArray(rawRisks)) return [];

  return rawRisks
    .slice(0, 8)
    .map((item): RiskItem | null => {
      if (typeof item === 'string') {
        const text = item.trim();
        if (!text) return null;
        return {
          label: text,
          level: 'medium',
          kind: isOperationalDiagnosticText(text) ? 'diagnostic' : 'financial',
        };
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
      return {
        label,
        level,
        kind: isOperationalDiagnosticText(label) ? 'diagnostic' : 'financial',
      };
    })
    .filter((item): item is RiskItem => Boolean(item));
}

export function RiskMetricsCard({ valuation, reportData }: RiskMetricsCardProps) {
  const parsedReportRisks = useMemo(() => extractReportRisks(reportData), [reportData]);
  const baselineRisks = useMemo(() => computeBaselineRisks(valuation), [valuation]);

  const financialRisks = useMemo(() => {
    const fromReport = parsedReportRisks.filter((item) => item.kind === 'financial');
    return fromReport.length > 0 ? fromReport : baselineRisks;
  }, [parsedReportRisks, baselineRisks]);

  const diagnosticCount = useMemo(
    () => parsedReportRisks.filter((item) => item.kind === 'diagnostic').length,
    [parsedReportRisks],
  );
  const diagnosticDetails = useMemo(
    () => parsedReportRisks
      .filter((item) => item.kind === 'diagnostic')
      .map((item) => item.label)
      .slice(0, 3),
    [parsedReportRisks],
  );

  const overallLevel = useMemo(() => {
    const highCount = financialRisks.filter((item) => item.level === 'high').length;
    const mediumCount = financialRisks.filter((item) => item.level === 'medium').length;
    if (highCount >= 2) return 'high' as RiskLevel;
    if (highCount >= 1 || mediumCount >= 2) return 'medium' as RiskLevel;
    return 'low' as RiskLevel;
  }, [financialRisks]);

  const overallStyle = RISK_STYLES[overallLevel];

  return (
    <div className="flex flex-col p-4 bg-fin-card rounded-xl border border-fin-border">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-medium text-fin-muted flex items-center gap-1">
          风险概览
          <CardInfoTip content="仅展示金融风险指标（Beta、52 周波动、估值压力等）" />
        </span>
        <span className={`text-2xs font-semibold px-2 py-0.5 rounded ${overallStyle.text} ${overallStyle.badge}`}>
          整体风险：{overallStyle.label}
        </span>
      </div>

      {diagnosticCount > 0 && (
        <div className="text-2xs text-fin-muted mb-3 flex items-center gap-1">
          <span>
            检测到 {diagnosticCount} 条执行诊断信息，已迁移至 <span className="text-fin-text">Agent 执行总览</span>。
          </span>
          <CardInfoTip
            icon="alert"
            size={13}
            content={(
              <div className="space-y-1">
                <div>原因：</div>
                {diagnosticDetails.map((detail, idx) => (
                  <div key={`${detail}-${idx}`} className="line-clamp-2">- {detail}</div>
                ))}
                <div>影响：当前卡片仅保留金融风险，诊断信息不参与风险等级计算。</div>
                <div>恢复：修复调度/证据问题后刷新，诊断条目会自动消失。</div>
              </div>
            )}
          />
        </div>
      )}

      <div className="space-y-2">
        {financialRisks.map((risk, idx) => {
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
