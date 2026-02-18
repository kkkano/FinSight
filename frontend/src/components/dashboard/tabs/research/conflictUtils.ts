import type { ReportIR } from '../../../../types';

export const CONFLICT_DIMENSIONS = [
  'valuation',
  'growth',
  'momentum',
  'macro',
  'sentiment',
  'risk',
] as const;

export type ConflictDimension = (typeof CONFLICT_DIMENSIONS)[number];

export interface ConflictMatrixRow {
  agent: string;
  cells: Record<ConflictDimension, string[]>;
}

const DIMENSION_LABELS: Record<ConflictDimension, string> = {
  valuation: '估值',
  growth: '增长',
  momentum: '动量',
  macro: '宏观',
  sentiment: '舆情',
  risk: '风险',
};

const FLAG_KEYWORDS: Record<ConflictDimension, string[]> = {
  valuation: ['valuation', 'pe', 'pb', '估值', '贵', '便宜'],
  growth: ['growth', 'revenue', 'earnings', '增长', '营收', '盈利'],
  momentum: ['momentum', 'trend', 'technical', 'rsi', 'macd', '动量', '趋势', '技术'],
  macro: ['macro', 'rates', 'fomc', 'cpi', 'gdp', '宏观', '利率', '通胀'],
  sentiment: ['sentiment', 'news', 'headline', '舆情', '新闻', '情绪'],
  risk: ['risk', 'drawdown', 'vol', 'volatility', '风险', '回撤', '波动'],
};

function resolveDimension(flag: string): ConflictDimension {
  const text = flag.toLowerCase();
  for (const dimension of CONFLICT_DIMENSIONS) {
    if (FLAG_KEYWORDS[dimension].some((keyword) => text.includes(keyword))) {
      return dimension;
    }
  }
  return 'risk';
}

function displayAgentName(agent: string): string {
  return agent.replace(/_agent$/i, '');
}

function emptyCells(): Record<ConflictDimension, string[]> {
  return {
    valuation: [],
    growth: [],
    momentum: [],
    macro: [],
    sentiment: [],
    risk: [],
  };
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : null;
}

export function extractConflictMatrixRows(report: ReportIR | Record<string, unknown> | null): ConflictMatrixRow[] {
  const root = asRecord(report);
  if (!root) return [];

  const diagnostics = asRecord(root.agent_diagnostics);
  if (!diagnostics) return [];

  const rows: ConflictMatrixRow[] = [];
  for (const [agent, rawInfo] of Object.entries(diagnostics)) {
    const info = asRecord(rawInfo);
    if (!info) continue;
    const flags = Array.isArray(info.conflict_flags)
      ? info.conflict_flags.filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
      : [];
    if (flags.length === 0) continue;

    const row: ConflictMatrixRow = {
      agent: displayAgentName(agent),
      cells: emptyCells(),
    };
    for (const flag of flags) {
      const dimension = resolveDimension(flag);
      row.cells[dimension].push(flag);
    }
    rows.push(row);
  }
  return rows;
}

export function extractConflictDisclosure(report: ReportIR | Record<string, unknown> | null): string {
  const root = asRecord(report);
  if (!root) return '';
  const disclosure = root.conflict_disclosure;
  return typeof disclosure === 'string' ? disclosure.trim() : '';
}

export function hasStructuredConflict(rows: ConflictMatrixRow[]): boolean {
  return rows.some((row) =>
    CONFLICT_DIMENSIONS.some((dimension) => row.cells[dimension].length > 0),
  );
}

export function dimensionLabel(dimension: ConflictDimension): string {
  return DIMENSION_LABELS[dimension];
}
