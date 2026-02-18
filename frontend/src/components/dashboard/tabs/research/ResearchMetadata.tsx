/**
 * ResearchMetadata - Display research report quality indicators.
 *
 * Shows confidence score, citation count, evidence quality, and conflict count
 * extracted from the latest report data.
 */
import type { LatestReportData } from '../../../../hooks/useLatestReport.ts';

interface ResearchMetadataProps {
  reportData: LatestReportData | null;
  loading?: boolean;
}

interface MetricCard {
  label: string;
  value: string;
  subLabel?: string;
  tone?: 'default' | 'warning';
}

function extractMetrics(reportData: LatestReportData): MetricCard[] {
  const report = reportData.report as Record<string, unknown>;
  const citations = reportData.citations ?? [];

  // Extract confidence score from various possible paths
  const confidence =
    (report?.confidence_score as number) ??
    (report?.quality_score as number) ??
    ((report?.metadata as Record<string, unknown>)?.confidence as number) ??
    null;

  // Citation count
  const citationCount = citations.length;

  // Evidence quality
  const evidenceQuality =
    (report?.evidence_quality as string) ??
    ((report?.metadata as Record<string, unknown>)?.evidence_quality as string) ??
    null;

  // Grounding rate
  const meta = (report?.meta as Record<string, unknown>) ?? {};
  const reportHints = (report?.report_hints as Record<string, unknown>) ?? {};
  const qualityHints = (reportHints?.quality as Record<string, unknown>) ?? {};
  const groundingFromMeta = (meta?.grounding as Record<string, unknown>)?.grounding_rate as number | undefined;
  const groundingFromHints = (reportHints?.grounding as Record<string, unknown>)?.grounding_rate as number | undefined;
  const groundingFromQualityHints = (qualityHints?.grounding as Record<string, unknown>)?.grounding_rate as number | undefined;
  const groundingRate =
    (report?.grounding_rate as number) ??
    groundingFromMeta ??
    groundingFromHints ??
    groundingFromQualityHints ??
    null;
  const groundingRateNormalized = typeof groundingRate === 'number' && Number.isFinite(groundingRate)
    ? Math.max(0, Math.min(1, groundingRate))
    : null;
  const groundingValue = groundingRateNormalized !== null
    ? `${Math.round(groundingRateNormalized * 100)}%`
    : '--';
  const groundingSubLabel = groundingRateNormalized === null
    ? undefined
    : groundingRateNormalized < 0.6
      ? '证据溯源偏低'
      : groundingRateNormalized < 0.75
        ? '证据溯源一般'
        : '证据溯源较好';
  const groundingTone: MetricCard['tone'] = groundingRateNormalized !== null && groundingRateNormalized < 0.6
    ? 'warning'
    : 'default';

  // Conflict count
  const conflicts = report?.conflicts as unknown[];
  const conflictCount = Array.isArray(conflicts) ? conflicts.length : 0;

  return [
    {
      label: '置信度',
      value: confidence !== null ? `${Math.round(confidence * 100)}%` : '--',
    },
    {
      label: '引用数量',
      value: citationCount > 0 ? String(citationCount) : '--',
    },
    {
      label: '证据质量',
      value: evidenceQuality ?? '--',
    },
    {
      label: '冲突数量',
      value: String(conflictCount),
      subLabel: conflictCount === 0 ? '无冲突' : undefined,
    },
    {
      label: '溯源率',
      value: groundingValue,
      subLabel: groundingSubLabel,
      tone: groundingTone,
    },
  ];
}

export function ResearchMetadata({ reportData, loading }: ResearchMetadataProps) {
  if (loading) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
        {[1, 2, 3, 4, 5].map((i) => (
          <div key={i} className="bg-fin-card border border-fin-border rounded-lg p-3 animate-pulse">
            <div className="h-3 bg-fin-border rounded w-16 mb-2" />
            <div className="h-5 bg-fin-border rounded w-12" />
          </div>
        ))}
      </div>
    );
  }

  if (!reportData) {
    return (
      <div className="bg-fin-card border border-fin-border rounded-lg p-4 text-center">
        <p className="text-sm text-fin-muted">尚未生成研究报告</p>
      </div>
    );
  }

  const metrics = extractMetrics(reportData);

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
      {metrics.map((metric) => (
        <div
          key={metric.label}
          className="bg-fin-card border border-fin-border rounded-lg p-3"
        >
          <div className="text-xs text-fin-muted mb-1">{metric.label}</div>
          <div className={`text-lg font-semibold ${metric.tone === 'warning' ? 'text-fin-warning' : 'text-fin-text'}`}>
            {metric.value}
          </div>
          {metric.subLabel ? (
            <div className="text-2xs text-fin-muted mt-0.5">{metric.subLabel}</div>
          ) : null}
        </div>
      ))}
    </div>
  );
}

export default ResearchMetadata;
