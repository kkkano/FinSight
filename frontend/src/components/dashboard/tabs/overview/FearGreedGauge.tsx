import { useMemo } from 'react';

import type { LatestReportData } from '../../../../hooks/useLatestReport';
import type { MacroSnapshotData } from '../../../../types/dashboard';
import { CardInfoTip } from '../../../ui/CardInfoTip';
import { asRecord } from '../../../../utils/record';

interface FearGreedGaugeProps {
  reportData?: LatestReportData | null;
  macroSnapshot?: MacroSnapshotData | null;
}

interface FearGreedValue {
  value: number | null;
  label: string;
  source: string;
  summary: string | null;
}

interface MacroMetric {
  label: string;
  value: string;
}

const scoreLabel = (value: number): string => {
  if (value <= 20) return '极度恐惧';
  if (value <= 40) return '恐惧';
  if (value <= 60) return '中性';
  if (value <= 80) return '贪婪';
  return '极度贪婪';
};

const extractFearGreedFromText = (text: string): number | null => {
  if (!text) return null;
  const normalized = text.replace(/\s+/g, ' ');
  const match = normalized.match(/(?:fear\s*&?\s*greed(?:\s*index)?|恐惧贪婪指数)[^0-9]{0,20}([0-9]{1,3})/i);
  if (!match) return null;
  const value = Number(match[1]);
  if (!Number.isFinite(value)) return null;
  return Math.max(0, Math.min(100, value));
};

const formatNumber = (value: unknown, digits = 1, suffix = ''): string | null => {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return null;
  return `${numeric.toFixed(digits)}${suffix}`;
};

function getMacroSummaryFromReport(reportData: LatestReportData | null | undefined): string | null {
  const report = asRecord(reportData?.report);
  const meta = asRecord(report?.meta);
  const summaries = Array.isArray(meta?.agent_summaries) ? meta.agent_summaries : [];

  for (const item of summaries) {
    const node = asRecord(item);
    if (!node || String(node.agent_name || '') !== 'macro_agent') continue;
    const summary = String(node.summary || '').trim();
    if (summary) return summary;
  }
  return null;
}

function resolveFearGreedFromReport(reportData: LatestReportData | null | undefined): FearGreedValue {
  const summary = getMacroSummaryFromReport(reportData);
  const parsedFromSummary = extractFearGreedFromText(summary || '');
  if (parsedFromSummary != null) {
    return {
      value: parsedFromSummary,
      label: scoreLabel(parsedFromSummary),
      source: '来源：macro_agent 摘要',
      summary,
    };
  }

  const report = asRecord(reportData?.report);
  const agentStatus = asRecord(report?.agent_status);
  const macroNode = asRecord(agentStatus?.macro_agent);
  const confidenceRaw = Number(macroNode?.confidence);
  if (Number.isFinite(confidenceRaw)) {
    const value = Math.max(0, Math.min(100, confidenceRaw <= 1 ? confidenceRaw * 100 : confidenceRaw));
    return {
      value,
      label: `${scoreLabel(value)}（近似）`,
      source: '来源：macro_agent 置信度近似',
      summary,
    };
  }

  return {
    value: null,
    label: '--',
    source: 'macro_agent 未提供情绪值',
    summary,
  };
}

function resolveFearGreedFromMacroSnapshot(macroSnapshot: MacroSnapshotData | null | undefined): FearGreedValue {
  if (!macroSnapshot) {
    return {
      value: null,
      label: '--',
      source: 'dashboard 宏观快照不可用',
      summary: null,
    };
  }

  const summary = String(macroSnapshot.sentiment_text || '').trim() || null;
  const directValue = Number(macroSnapshot.fear_greed_index);
  if (Number.isFinite(directValue)) {
    const normalized = Math.max(0, Math.min(100, directValue));
    return {
      value: normalized,
      label: String(macroSnapshot.fear_greed_label || '').trim() || scoreLabel(normalized),
      source: '来源：/api/dashboard macro_snapshot',
      summary,
    };
  }

  const parsedFromSummary = extractFearGreedFromText(summary || '');
  if (parsedFromSummary != null) {
    return {
      value: parsedFromSummary,
      label: scoreLabel(parsedFromSummary),
      source: '来源：macro_snapshot.sentiment_text 解析',
      summary,
    };
  }

  return {
    value: null,
    label: '--',
    source: 'macro_snapshot 未包含 Fear & Greed',
    summary,
  };
}

function buildMacroMetrics(macroSnapshot: MacroSnapshotData | null | undefined): MacroMetric[] {
  if (!macroSnapshot) return [];

  const metrics: MacroMetric[] = [];
  const fedRate = formatNumber(macroSnapshot.fed_rate, 2, '%');
  if (fedRate) metrics.push({ label: '联邦利率', value: fedRate });

  const cpi = formatNumber(macroSnapshot.cpi, 2, '%');
  if (cpi) metrics.push({ label: 'CPI', value: cpi });

  const unemployment = formatNumber(macroSnapshot.unemployment, 2, '%');
  if (unemployment) metrics.push({ label: '失业率', value: unemployment });

  const tenYear = formatNumber(macroSnapshot.treasury_10y, 2, '%');
  if (tenYear) metrics.push({ label: '10Y 美债', value: tenYear });

  const spread = formatNumber(macroSnapshot.yield_spread, 2, '%');
  if (spread) metrics.push({ label: '期限利差', value: spread });

  return metrics.slice(0, 3);
}

export function FearGreedGauge({ reportData, macroSnapshot }: FearGreedGaugeProps) {
  const fearGreed = useMemo(() => {
    const fromReport = resolveFearGreedFromReport(reportData);
    if (fromReport.value != null) return fromReport;

    const fromSnapshot = resolveFearGreedFromMacroSnapshot(macroSnapshot);
    if (fromSnapshot.value != null) return fromSnapshot;

    if (fromReport.summary) return fromReport;
    return fromSnapshot;
  }, [reportData, macroSnapshot]);

  const pointerLeft = fearGreed.value == null ? 50 : Math.max(0, Math.min(100, fearGreed.value));
  const macroMetrics = useMemo(() => buildMacroMetrics(macroSnapshot), [macroSnapshot]);
  const summaryText = fearGreed.summary || '暂无 macro_agent 摘要';

  return (
    <div className="flex flex-col p-4 bg-fin-card rounded-xl border border-fin-border">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-fin-muted flex items-center gap-1">
          市场情绪（Fear &amp; Greed）
          <CardInfoTip content="来源：macro_agent 摘要 > 置信度近似 > macro_snapshot API" />
        </span>
        <span className="text-xs font-semibold text-fin-text">{fearGreed.label}</span>
      </div>

      <div className="mt-2 flex items-end gap-2">
        <span className="text-3xl font-semibold text-fin-text tabular-nums">
          {fearGreed.value == null ? '--' : Math.round(fearGreed.value)}
        </span>
        <span className="text-xs text-fin-muted mb-1">/ 100</span>
      </div>

      <div className="mt-3">
        <div className="h-2 rounded-full bg-gradient-to-r from-fin-danger via-fin-warning to-fin-success relative">
          <span
            className="absolute top-1/2 h-3 w-3 -translate-y-1/2 rounded-full border border-fin-card bg-fin-text shadow"
            style={{ left: `calc(${pointerLeft}% - 6px)` }}
          />
        </div>
        <div className="mt-1 flex justify-between text-2xs text-fin-muted">
          <span>恐惧</span>
          <span>中性</span>
          <span>贪婪</span>
        </div>
      </div>

      <div className="mt-3 rounded-lg border border-fin-border/60 bg-fin-border/20 p-2">
        <div className="text-2xs text-fin-muted">{fearGreed.source}</div>
        <div className="mt-1 text-xs text-fin-text/80 leading-relaxed line-clamp-3">{summaryText}</div>
      </div>

      {macroMetrics.length > 0 && (
        <div className="mt-3 grid grid-cols-2 gap-2">
          {macroMetrics.map((metric) => (
            <div key={metric.label} className="rounded-md border border-fin-border/50 px-2 py-1">
              <div className="text-2xs text-fin-muted">{metric.label}</div>
              <div className="text-xs text-fin-text tabular-nums">{metric.value}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default FearGreedGauge;
