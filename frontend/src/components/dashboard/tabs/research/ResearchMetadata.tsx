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

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const asFiniteNumber = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null;

const formatRatioPercent = (value: number): string => {
  const normalized = Math.max(0, Math.min(1, value));
  return `${Math.round(normalized * 100)}%`;
};

const formatEvidenceQuality = (value: unknown): string | null => {
  if (typeof value === 'string') return value;
  const numericValue = asFiniteNumber(value);
  if (numericValue !== null) return formatRatioPercent(numericValue);
  if (!isRecord(value)) return null;

  const overallScore = asFiniteNumber(value.overall_score);
  if (overallScore !== null) return formatRatioPercent(overallScore);
  return typeof value.status === 'string' ? value.status : null;
};

const extractAgentQualityMetric = (value: unknown): MetricCard | null => {
  if (!isRecord(value)) return null;
  const agentQuality = isRecord(value.agent_quality) ? value.agent_quality : null;
  if (!agentQuality) return null;

  const metrics = isRecord(agentQuality.metrics) ? agentQuality.metrics : {};
  const supportedClaimCount = asFiniteNumber(metrics.supported_claim_count);
  const claimCount = asFiniteNumber(metrics.claim_count);
  const status = typeof agentQuality.status === 'string' ? agentQuality.status : '--';
  const subLabel = supportedClaimCount !== null && claimCount !== null
    ? `${supportedClaimCount}/${claimCount} claims`
    : undefined;

  return {
    label: 'Agent 质量',
    value: status,
    subLabel,
    tone: status === 'fail' || status === 'warn' ? 'warning' : 'default',
  };
};

const normalizeLayerBreakdown = (value: unknown): string | null => {
  if (Array.isArray(value)) {
    const parts = value
      .map((item) => {
        if (!isRecord(item)) return null;
        const layer = typeof item.layer === 'string' ? item.layer : null;
        const count = asFiniteNumber(item.count);
        return layer && count !== null ? `${layer} ${count}` : null;
      })
      .filter((item): item is string => Boolean(item));
    return parts.length > 0 ? parts.join(' · ') : null;
  }

  if (isRecord(value)) {
    const parts = ['memory', 'ws', 'kb']
      .map((layer) => {
        const count = asFiniteNumber(value[layer]);
        return count !== null ? `${layer} ${count}` : null;
      })
      .filter((item): item is string => Boolean(item));
    return parts.length > 0 ? parts.join(' · ') : null;
  }

  return null;
};

function extractMetrics(reportData: LatestReportData): MetricCard[] {
  const report = reportData.report as Record<string, unknown>;
  const citations = reportData.citations ?? [];
  const metadata = isRecord(report?.metadata) ? report.metadata : {};

  // Extract confidence score from various possible paths
  const confidence =
    (report?.confidence_score as number) ??
    (report?.quality_score as number) ??
    (metadata?.confidence as number) ??
    null;

  // Citation count
  const citationCount = citations.length;

  // Evidence quality
  const rawEvidenceQuality = report?.evidence_quality ?? metadata?.evidence_quality;
  const evidenceQuality =
    formatEvidenceQuality(rawEvidenceQuality) ??
    '--';

  // Grounding rate
  const meta = isRecord(report?.meta) ? report.meta : {};
  const reportHints = isRecord(report?.report_hints) ? report.report_hints : {};
  const qualityHints = isRecord(reportHints?.quality) ? reportHints.quality : {};
  const groundingMeta = isRecord(meta?.grounding) ? meta.grounding : {};
  const groundingHints = isRecord(reportHints?.grounding) ? reportHints.grounding : {};
  const groundingQualityHints = isRecord(qualityHints?.grounding) ? qualityHints.grounding : {};
  const groundingFromMeta = groundingMeta?.grounding_rate as number | undefined;
  const groundingFromHints = groundingHints?.grounding_rate as number | undefined;
  const groundingFromQualityHints = groundingQualityHints?.grounding_rate as number | undefined;
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

  const agentQualityMetric = extractAgentQualityMetric(rawEvidenceQuality);
  const layerBreakdown =
    normalizeLayerBreakdown(groundingHints?.layer_hit_breakdown) ??
    normalizeLayerBreakdown(groundingQualityHints?.layer_hit_breakdown) ??
    normalizeLayerBreakdown(groundingMeta?.layer_hit_breakdown) ??
    normalizeLayerBreakdown(report?.layer_hit_breakdown);

  const metrics: MetricCard[] = [
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
      value: evidenceQuality,
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

  if (agentQualityMetric) {
    metrics.push(agentQualityMetric);
  }

  if (layerBreakdown) {
    metrics.push({
      label: 'RAG 分层',
      value: '命中分布',
      subLabel: layerBreakdown,
    });
  }

  return metrics;
}

const metricGridClassName = 'grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3';

export function ResearchMetadata({ reportData, loading }: ResearchMetadataProps) {
  if (loading) {
    return (
      <div className={metricGridClassName}>
        {[1, 2, 3, 4, 5, 6].map((i) => (
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
    <div className={metricGridClassName}>
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
