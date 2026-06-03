/**
 * P2-7：成本审计页面的纯数据层（类型 + 格式化 + echarts option 构建）。
 *
 * 抽出纯函数便于单测（不依赖 DOM / 网络），页面组件只负责拉数据与渲染。
 */

export type CostAuditSourceBreakdown = {
  tokens: number;
  cost_usd: number;
  count: number;
};

export type CostAuditDailyPoint = {
  date: string;
  total_tokens: number;
  total_cost_usd: number;
  request_count: number;
  by_source: Record<string, CostAuditSourceBreakdown>;
};

export type CostAuditTopRequest = {
  id: number;
  created_at: string;
  session_id: string;
  source: string;
  total_tokens: number;
  prompt_tokens: number;
  completion_tokens: number;
  llm_calls: number;
  cost_usd: number;
  model_breakdown: Record<string, { prompt?: number; completion?: number; calls?: number }>;
};

export type CostAuditData = {
  days: number;
  daily: CostAuditDailyPoint[];
  top_requests: CostAuditTopRequest[];
  total_cost_usd: number;
  total_tokens: number;
  request_count: number;
};

export const EMPTY_COST_AUDIT: CostAuditData = {
  days: 7,
  daily: [],
  top_requests: [],
  total_cost_usd: 0,
  total_tokens: 0,
  request_count: 0,
};

/** 从后端响应（{status, data, timestamp} 或裸 data）归一化为 CostAuditData。 */
export const normalizeCostAudit = (payload: unknown): CostAuditData => {
  const root = (payload && typeof payload === 'object' ? payload : {}) as Record<string, unknown>;
  const data = (root.data && typeof root.data === 'object' ? root.data : root) as Record<string, unknown>;

  const daily = Array.isArray(data.daily)
    ? (data.daily as unknown[]).map((item) => normalizeDailyPoint(item))
    : [];
  const topRequests = Array.isArray(data.top_requests)
    ? (data.top_requests as unknown[]).map((item) => normalizeTopRequest(item))
    : [];

  return {
    days: toNumber(data.days, 7),
    daily,
    top_requests: topRequests,
    total_cost_usd: toNumber(data.total_cost_usd, 0),
    total_tokens: toNumber(data.total_tokens, 0),
    request_count: toNumber(data.request_count, 0),
  };
};

const normalizeDailyPoint = (item: unknown): CostAuditDailyPoint => {
  const row = (item && typeof item === 'object' ? item : {}) as Record<string, unknown>;
  const bySourceRaw = (row.by_source && typeof row.by_source === 'object' ? row.by_source : {}) as Record<string, unknown>;
  const bySource: Record<string, CostAuditSourceBreakdown> = {};
  Object.entries(bySourceRaw).forEach(([key, value]) => {
    const entry = (value && typeof value === 'object' ? value : {}) as Record<string, unknown>;
    bySource[key] = {
      tokens: toNumber(entry.tokens, 0),
      cost_usd: toNumber(entry.cost_usd, 0),
      count: toNumber(entry.count, 0),
    };
  });
  return {
    date: String(row.date || ''),
    total_tokens: toNumber(row.total_tokens, 0),
    total_cost_usd: toNumber(row.total_cost_usd, 0),
    request_count: toNumber(row.request_count, 0),
    by_source: bySource,
  };
};

const normalizeTopRequest = (item: unknown): CostAuditTopRequest => {
  const row = (item && typeof item === 'object' ? item : {}) as Record<string, unknown>;
  const breakdown = (row.model_breakdown && typeof row.model_breakdown === 'object'
    ? row.model_breakdown
    : {}) as CostAuditTopRequest['model_breakdown'];
  return {
    id: toNumber(row.id, 0),
    created_at: String(row.created_at || ''),
    session_id: String(row.session_id || ''),
    source: String(row.source || 'other'),
    total_tokens: toNumber(row.total_tokens, 0),
    prompt_tokens: toNumber(row.prompt_tokens, 0),
    completion_tokens: toNumber(row.completion_tokens, 0),
    llm_calls: toNumber(row.llm_calls, 0),
    cost_usd: toNumber(row.cost_usd, 0),
    model_breakdown: breakdown,
  };
};

const toNumber = (value: unknown, fallback: number): number => {
  const n = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(n) ? n : fallback;
};

/** 紧凑数字（1.2k / 3.4M）。 */
export const formatCompactNumber = (value: number): string => {
  if (!Number.isFinite(value)) return '—';
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(2)}M`;
  if (Math.abs(value) >= 1_000) return `${(value / 1_000).toFixed(1)}k`;
  return String(Math.round(value));
};

/** 成本（USD）：小额保留更多位，避免显示为 $0.00。 */
export const formatUsd = (value: number): string => {
  if (!Number.isFinite(value)) return '—';
  if (value === 0) return '$0';
  if (value < 0.01) return `$${value.toFixed(5)}`;
  return `$${value.toFixed(2)}`;
};

export const formatDateTime = (value?: string | null): string => {
  if (!value) return '—';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return parsed.toLocaleString();
};

/** 来源中文标签（统一口径，未知归 other）。 */
export const SOURCE_LABELS: Record<string, string> = {
  chat: '对话',
  report: '报告',
  monitor_l2: '盯盘深析',
  dashboard: '仪表盘',
  execute_run: '执行',
  execute_resume: '续跑',
  other: '其他',
};

export const sourceLabel = (source: string): string => SOURCE_LABELS[source] || source || '其他';

type DailyChartTheme = {
  text: string;
  muted: string;
  border: string;
  grid: string;
  primary: string;
  warning: string;
  tooltipBackground: string;
  tooltipBorder: string;
  tooltipText: string;
};

/**
 * 构建「每日成本 + token」双轴 echarts option。
 * 柱状=成本（USD，左轴），折线=token（右轴）。纯函数，不触碰 DOM。
 */
export const buildDailyCostOption = (daily: CostAuditDailyPoint[], theme: DailyChartTheme) => {
  const dates = daily.map((d) => d.date);
  const costs = daily.map((d) => Number(d.total_cost_usd.toFixed(6)));
  const tokens = daily.map((d) => d.total_tokens);

  return {
    grid: { left: 56, right: 56, top: 28, bottom: 32 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: theme.tooltipBackground,
      borderColor: theme.tooltipBorder,
      textStyle: { color: theme.tooltipText, fontSize: 12 },
    },
    legend: {
      data: ['成本 (USD)', 'Token'],
      textStyle: { color: theme.muted, fontSize: 11 },
      top: 0,
    },
    xAxis: {
      type: 'category',
      data: dates,
      axisLabel: { color: theme.muted, fontSize: 11 },
      axisLine: { lineStyle: { color: theme.border } },
    },
    yAxis: [
      {
        type: 'value',
        name: 'USD',
        nameTextStyle: { color: theme.muted, fontSize: 10 },
        axisLabel: { color: theme.muted, fontSize: 11 },
        splitLine: { lineStyle: { color: theme.grid } },
      },
      {
        type: 'value',
        name: 'Token',
        nameTextStyle: { color: theme.muted, fontSize: 10 },
        axisLabel: { color: theme.muted, fontSize: 11, formatter: (v: number) => formatCompactNumber(v) },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: '成本 (USD)',
        type: 'bar',
        yAxisIndex: 0,
        data: costs,
        itemStyle: { color: theme.primary, borderRadius: [4, 4, 0, 0] },
        barMaxWidth: 28,
      },
      {
        name: 'Token',
        type: 'line',
        yAxisIndex: 1,
        data: tokens,
        smooth: true,
        symbol: 'circle',
        symbolSize: 6,
        lineStyle: { color: theme.warning, width: 2 },
        itemStyle: { color: theme.warning },
      },
    ],
  };
};
