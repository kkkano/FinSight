import type {
  SmartChartBlock,
  SmartChartData,
  SmartChartOhlcPoint,
  SmartChartType,
} from '../components/SmartChart';
import type { ExecutionRun } from '../types/execution';
import type { ReportIR, ResearchClaim } from '../types/index';

export type DashboardDeepDiveTab = 'overview' | 'financial' | 'news' | 'peers' | 'technical';

export interface DashboardAgentChartSpec {
  type: SmartChartType;
  title: string;
  data: SmartChartData;
}

export interface DashboardAgentOverlay {
  runId: string;
  status: ExecutionRun['status'];
  summary: string;
  claims: ResearchClaim[];
  chartSpecs?: DashboardAgentChartSpec[];
  updatedAt: string;
}

const SMART_CHART_TYPES: readonly SmartChartType[] = [
  'bar',
  'line',
  'pie',
  'scatter',
  'gauge',
  'candlestick',
  'price_volume',
  'rs_line',
  'waterfall',
  'heatmap',
  'radar',
  'valuation_band',
  'bubble',
  'drawdown',
  'scenario',
];

export function buildDashboardOverlayKey(symbol: string, tab: DashboardDeepDiveTab): string {
  return `${String(symbol || '').trim().toUpperCase()}_${tab}`;
}

/**
 * 防御：清洗 startDeepDive 的 override 问题参数。
 * onClick={startDeepDive} 这种直接绑定会让 React 把 MouseEvent 传进来——
 * 事件对象一旦进入请求体，JSON.stringify 会因 React fiber 循环引用而崩溃。
 * 只有非空字符串才是合法的 override 问题，其余一律视为未提供。
 */
export function sanitizeOverrideQuestion(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function asText(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const text = value.trim();
  return text || null;
}

function asNumber(value: unknown): number | null {
  const number = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(number) ? number : null;
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => String(item ?? '').trim())
    .filter(Boolean);
}

function asNumberArray(value: unknown): number[] | null {
  if (!Array.isArray(value)) return null;
  const rows = value
    .map(asNumber)
    .filter((item): item is number => item !== null);
  return rows.length > 0 ? rows : null;
}

function isSmartChartType(value: unknown): value is SmartChartType {
  return typeof value === 'string' && (SMART_CHART_TYPES as readonly string[]).includes(value);
}

function normalizeOhlc(value: unknown): SmartChartOhlcPoint[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const rows: SmartChartOhlcPoint[] = [];

  for (const item of value) {
    if (!Array.isArray(item) || item.length < 4) return undefined;
    const open = asNumber(item[0]);
    const close = asNumber(item[1]);
    const low = asNumber(item[2]);
    const high = asNumber(item[3]);
    if (open === null || close === null || low === null || high === null) return undefined;
    rows.push([open, close, low, high]);
  }

  return rows.length > 0 ? rows : undefined;
}

function normalizeNamedNumberSeries(value: unknown): Array<{ name: string; values: number[]; unit?: string }> | undefined {
  if (!Array.isArray(value)) return undefined;
  const rows = value.flatMap((item, index): Array<{ name: string; values: number[]; unit?: string }> => {
    if (!isRecord(item)) return [];
    const values = asNumberArray(item.values);
    if (!values) return [];
    const name = asText(item.name) ?? `Series ${index + 1}`;
    const unit = asText(item.unit);
    return [{ name, values, ...(unit ? { unit } : {}) }];
  });
  return rows.length > 0 ? rows : undefined;
}

function normalizeEvents(value: unknown): SmartChartData['events'] | undefined {
  if (!Array.isArray(value)) return undefined;
  const events = value.flatMap((item): NonNullable<SmartChartData['events']> => {
    if (!isRecord(item)) return [];
    const label = asText(item.label) ?? asText(item.name) ?? asText(item.title);
    if (!label) return [];
    const dateValue = item.date ?? item.ts ?? item.time;
    const date = typeof dateValue === 'string' || typeof dateValue === 'number'
      ? String(dateValue)
      : undefined;
    const index = asNumber(item.index) ?? undefined;
    const eventValue = asNumber(item.value) ?? undefined;
    const kind = asText(item.kind) ?? asText(item.type) ?? undefined;
    return [{
      label,
      ...(date ? { date } : {}),
      ...(index !== undefined ? { index } : {}),
      ...(eventValue !== undefined ? { value: eventValue } : {}),
      ...(kind ? { kind } : {}),
    }];
  });
  return events.length > 0 ? events : undefined;
}

function normalizeChartData(value: unknown): SmartChartData | null {
  if (!isRecord(value)) return null;

  const labels = asStringArray(value.labels);
  const values = asNumberArray(value.values);
  const ohlc = normalizeOhlc(value.ohlc);
  const series = normalizeNamedNumberSeries(value.series);
  const fallbackValues = values ?? ohlc?.map((row) => row[1]) ?? series?.[0]?.values ?? null;
  if (labels.length === 0 || !fallbackValues || fallbackValues.length === 0) return null;

  const volume = asNumberArray(value.volume);
  const bands = normalizeNamedNumberSeries(value.bands);
  const events = normalizeEvents(value.events);
  const unit = asText(value.unit);

  return {
    labels,
    values: fallbackValues,
    ...(unit ? { unit } : {}),
    ...(series ? { series } : {}),
    ...(ohlc ? { ohlc } : {}),
    ...(volume ? { volume } : {}),
    ...(bands ? { bands } : {}),
    ...(events ? { events } : {}),
  };
}

function normalizeChartSpecs(value: unknown): DashboardAgentChartSpec[] {
  if (!Array.isArray(value)) return [];

  return value.flatMap((item): DashboardAgentChartSpec[] => {
    if (!isRecord(item) || !isSmartChartType(item.type)) return [];
    const title = asText(item.title) ?? 'Agent chart';
    const data = normalizeChartData(item.data);
    if (!data) return [];
    return [{ type: item.type, title, data }];
  }).slice(0, 4);
}

function normalizeClaims(value: unknown): ResearchClaim[] {
  if (!Array.isArray(value)) return [];

  return value.flatMap((item, index): ResearchClaim[] => {
    if (!isRecord(item)) return [];
    const claim = asText(item.claim) ?? asText(item.text) ?? asText(item.summary);
    if (!claim) return [];
    const claimId = asText(item.claim_id) ?? asText(item.id) ?? `claim-${index + 1}`;
    return [{
      ...item,
      claim_id: claimId,
      claim,
    } as ResearchClaim];
  });
}

function nestedRecord(root: Record<string, unknown>, key: string): Record<string, unknown> | null {
  const value = root[key];
  return isRecord(value) ? value : null;
}

function firstChartSpecsFromContainer(container: unknown): DashboardAgentChartSpec[] {
  if (!isRecord(container)) return [];

  const direct = normalizeChartSpecs(container.chartSpecs ?? container.chart_specs);
  if (direct.length > 0) return direct;

  const overlay = nestedRecord(container, 'dashboard_overlay');
  const overlaySpecs = normalizeChartSpecs(overlay?.chartSpecs ?? overlay?.chart_specs);
  if (overlaySpecs.length > 0) return overlaySpecs;

  const artifacts = nestedRecord(container, 'artifacts');
  const artifactDirect = normalizeChartSpecs(artifacts?.chartSpecs ?? artifacts?.chart_specs);
  if (artifactDirect.length > 0) return artifactDirect;

  const artifactOverlay = artifacts ? nestedRecord(artifacts, 'dashboard_overlay') : null;
  return normalizeChartSpecs(artifactOverlay?.chartSpecs ?? artifactOverlay?.chart_specs);
}

function extractChartSpecs(report: ReportIR | null, doneMeta: unknown): DashboardAgentChartSpec[] {
  const fromReport = firstChartSpecsFromContainer(report);
  if (fromReport.length > 0) return fromReport;

  if (isRecord(report?.meta)) {
    const fromMeta = firstChartSpecsFromContainer(report.meta);
    if (fromMeta.length > 0) return fromMeta;
  }

  const fromDoneMeta = firstChartSpecsFromContainer(doneMeta);
  if (fromDoneMeta.length > 0) return fromDoneMeta;

  if (isRecord(doneMeta)) {
    const doneReport = doneMeta.report;
    const fromDoneReport = firstChartSpecsFromContainer(doneReport);
    if (fromDoneReport.length > 0) return fromDoneReport;
  }

  return [];
}

function extractClaims(report: ReportIR | null): ResearchClaim[] {
  if (!report) return [];
  const reportRecord = report as unknown as Record<string, unknown>;

  const directClaims = normalizeClaims(reportRecord.claims);
  if (directClaims.length > 0) return directClaims;

  const ledgerClaims = normalizeClaims(report.evidence_ledger?.claims);
  if (ledgerClaims.length > 0) return ledgerClaims;

  const artifactLedger = isRecord(report.artifacts?.evidence_ledger)
    ? report.artifacts.evidence_ledger
    : null;
  const artifactClaims = normalizeClaims(artifactLedger?.claims);
  if (artifactClaims.length > 0) return artifactClaims;

  const meta = isRecord(report.meta) ? report.meta : null;
  const metaOverlay = meta ? nestedRecord(meta, 'dashboard_overlay') : null;
  return normalizeClaims(metaOverlay?.claims);
}

function latestDoneMeta(run: ExecutionRun): unknown {
  const doneEvent = [...run.timeline]
    .reverse()
    .find((event) => event.eventType === 'done' || event.stage === 'done');
  return doneEvent?.raw;
}

function summarizeRun(run: ExecutionRun): string {
  if (run.status === 'error') return run.error || 'Agent 深挖失败，请稍后重试。';
  if (run.status === 'cancelled') return 'Agent 深挖已取消。';
  if (run.status === 'interrupted') return run.currentStep || 'Agent 深挖等待确认。';
  if (run.status === 'running') return run.currentStep || 'Agent 深挖正在执行。';
  return (
    asText(run.report?.summary)
    ?? asText(run.streamedContent)
    ?? 'Agent 深挖已完成，但未返回可展示摘要。'
  );
}

export function buildDashboardAgentOverlay(
  run: ExecutionRun,
  updatedAt = new Date().toISOString(),
): DashboardAgentOverlay {
  const chartSpecs = extractChartSpecs(run.report, latestDoneMeta(run));
  return {
    runId: run.runId,
    status: run.status,
    summary: summarizeRun(run),
    claims: extractClaims(run.report),
    ...(chartSpecs.length > 0 ? { chartSpecs } : {}),
    updatedAt,
  };
}

export function dashboardChartSpecsToBlocks(
  chartSpecs: DashboardAgentChartSpec[] | undefined,
): SmartChartBlock[] {
  return (chartSpecs ?? []).map((spec) => ({
    mode: 'inline',
    type: spec.type,
    title: spec.title,
    dataJson: JSON.stringify(spec.data),
  }));
}
