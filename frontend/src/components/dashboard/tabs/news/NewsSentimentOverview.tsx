/**
 * NewsSentimentOverview - 舆情仪表盘总览。
 *
 * 当前 Dashboard REST 只暴露新闻列表，尚未直连 NewsAgent 的聚合快照。
 * 因此这里仅基于单条新闻的 sentiment/impact/reliability 字段做客户端聚合。
 */
import { useMemo } from 'react';
import ReactECharts from 'echarts-for-react';
import { Activity, Flame, Minus, RadioTower, TrendingDown, TrendingUp } from 'lucide-react';

import { useChartTheme, type ChartTheme } from '../../../../hooks/useChartTheme';
import type { NewsItem, NewsTimeRange } from '../../../../types/dashboard';
import {
  classifySentiment,
  deriveImpactLevel,
  formatNewsTime,
  type SentimentType,
} from '../../../../utils/news';

type TrendDirection = 'up' | 'down' | 'flat' | 'insufficient';

interface SentimentBucket {
  label: string;
  timestamp: number;
  bullish: number;
  neutral: number;
  bearish: number;
  score: number;
}

interface SentimentOverviewStats {
  total: number;
  bullish: number;
  neutral: number;
  bearish: number;
  bullishPct: number;
  neutralPct: number;
  bearishPct: number;
  score: number;
  biasLabel: string;
  heatScore: number;
  heatLabel: string;
  highImpactCount: number;
  avgReliability: number | null;
  trendDirection: TrendDirection;
  trendLabel: string;
  trendDelta: number | null;
  timeline: SentimentBucket[];
  catalysts: CatalystEvent[];
}

interface CatalystEvent {
  id: string;
  title: string;
  source: string;
  ts: string;
  sentiment: SentimentType;
  impactScore: number;
}

interface NewsSentimentOverviewProps {
  news: NewsItem[];
  timeRange: NewsTimeRange;
  ticker?: string;
}

const TIME_RANGE_LABELS: Record<NewsTimeRange, string> = {
  '24h': '近24小时',
  '7d': '近7天',
  '30d': '近30天',
};

const SENTIMENT_LABELS: Record<SentimentType, string> = {
  bullish: '看多',
  neutral: '中性',
  bearish: '看空',
};

const SENTIMENT_TONE: Record<SentimentType, string> = {
  bullish: 'text-fin-success',
  neutral: 'text-fin-muted',
  bearish: 'text-fin-danger',
};

const SENTIMENT_DOT: Record<SentimentType, string> = {
  bullish: 'bg-fin-success',
  neutral: 'bg-fin-muted',
  bearish: 'bg-fin-danger',
};

const clamp = (value: number, min: number, max: number): number =>
  Math.max(min, Math.min(max, value));

const toPct = (value: number, total: number): number =>
  total > 0 ? Math.round((value / total) * 100) : 0;

const parseTimestamp = (value: string): number | null => {
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? timestamp : null;
};

const sentimentValue = (sentiment: SentimentType): number => {
  if (sentiment === 'bullish') return 1;
  if (sentiment === 'bearish') return -1;
  return 0;
};

const impactValue = (item: NewsItem): number => {
  if (typeof item.impact_score === 'number') {
    return clamp(item.impact_score, 0, 1);
  }
  const level = deriveImpactLevel(item);
  if (level === 'high') return 0.82;
  if (level === 'medium') return 0.52;
  return 0.24;
};

const itemWeight = (item: NewsItem): number => {
  const reliability = clamp(item.source_reliability ?? 0.6, 0, 1);
  const impact = impactValue(item);
  return 0.45 + reliability * 0.3 + impact * 0.25;
};

const formatSignedScore = (value: number): string =>
  `${value > 0 ? '+' : ''}${Math.round(value)}`;

const formatBucketLabel = (timestamp: number, timeRange: NewsTimeRange): string => {
  const date = new Date(timestamp);
  if (timeRange === '24h') {
    return `${String(date.getHours()).padStart(2, '0')}:00`;
  }
  return `${date.getMonth() + 1}/${date.getDate()}`;
};

const bucketTimestamp = (timestamp: number, timeRange: NewsTimeRange): number => {
  const date = new Date(timestamp);
  if (timeRange === '24h') {
    date.setMinutes(0, 0, 0);
    date.setHours(Math.floor(date.getHours() / 4) * 4);
    return date.getTime();
  }
  date.setHours(0, 0, 0, 0);
  return date.getTime();
};

const buildTimeline = (news: NewsItem[], timeRange: NewsTimeRange): SentimentBucket[] => {
  const grouped = new Map<
    number,
    {
      bullish: number;
      neutral: number;
      bearish: number;
      weightedScore: number;
      weight: number;
    }
  >();

  for (const item of news) {
    const timestamp = parseTimestamp(item.ts);
    if (timestamp == null) continue;

    const key = bucketTimestamp(timestamp, timeRange);
    const sentiment = classifySentiment(item);
    const weight = itemWeight(item);
    const next = grouped.get(key) ?? {
      bullish: 0,
      neutral: 0,
      bearish: 0,
      weightedScore: 0,
      weight: 0,
    };

    next[sentiment] += 1;
    next.weightedScore += sentimentValue(sentiment) * weight;
    next.weight += weight;
    grouped.set(key, next);
  }

  return [...grouped.entries()]
    .sort(([a], [b]) => a - b)
    .map(([timestamp, bucket]) => ({
      label: formatBucketLabel(timestamp, timeRange),
      timestamp,
      bullish: bucket.bullish,
      neutral: bucket.neutral,
      bearish: bucket.bearish,
      score: bucket.weight > 0 ? Math.round((bucket.weightedScore / bucket.weight) * 100) : 0,
    }));
};

const average = (values: number[]): number => {
  if (values.length === 0) return 0;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
};

const resolveTrend = (timeline: SentimentBucket[]): {
  direction: TrendDirection;
  label: string;
  delta: number | null;
} => {
  if (timeline.length < 2) {
    return { direction: 'insufficient', label: '样本不足', delta: null };
  }

  const midpoint = Math.ceil(timeline.length / 2);
  const firstHalf = timeline.slice(0, midpoint).map((bucket) => bucket.score);
  const secondHalf = timeline.slice(midpoint).map((bucket) => bucket.score);
  if (secondHalf.length === 0) {
    return { direction: 'insufficient', label: '样本不足', delta: null };
  }

  const delta = average(secondHalf) - average(firstHalf);
  if (delta >= 12) return { direction: 'up', label: '转暖', delta };
  if (delta <= -12) return { direction: 'down', label: '走弱', delta };
  return { direction: 'flat', label: '震荡', delta };
};

const buildCatalysts = (news: NewsItem[]): CatalystEvent[] => {
  const highImpact = news
    .filter((item) => deriveImpactLevel(item) === 'high' || (item.impact_score ?? 0) >= 0.6)
    .sort((a, b) => {
      const scoreDelta = impactValue(b) - impactValue(a);
      if (Math.abs(scoreDelta) > 0.001) return scoreDelta;
      return (parseTimestamp(b.ts) ?? 0) - (parseTimestamp(a.ts) ?? 0);
    });

  return highImpact.slice(0, 5).map((item, index) => ({
    id: `${item.title}-${item.source}-${item.ts}-${index}`,
    title: item.title,
    source: item.source ?? '',
    ts: item.ts,
    sentiment: classifySentiment(item),
    impactScore: impactValue(item),
  }));
};

const computeOverviewStats = (
  news: NewsItem[],
  timeRange: NewsTimeRange,
): SentimentOverviewStats => {
  let bullish = 0;
  let neutral = 0;
  let bearish = 0;
  let weightedScore = 0;
  let totalWeight = 0;
  let reliabilitySum = 0;
  let reliabilityCount = 0;
  let impactSum = 0;
  let highImpactCount = 0;

  for (const item of news) {
    const sentiment = classifySentiment(item);
    const weight = itemWeight(item);
    const impact = impactValue(item);

    if (sentiment === 'bullish') bullish += 1;
    else if (sentiment === 'bearish') bearish += 1;
    else neutral += 1;

    weightedScore += sentimentValue(sentiment) * weight;
    totalWeight += weight;
    impactSum += impact;
    if (deriveImpactLevel(item) === 'high' || impact >= 0.6) {
      highImpactCount += 1;
    }

    if (typeof item.source_reliability === 'number') {
      reliabilitySum += clamp(item.source_reliability, 0, 1);
      reliabilityCount += 1;
    }
  }

  const total = news.length;
  const score = totalWeight > 0 ? Math.round((weightedScore / totalWeight) * 100) : 0;
  const avgImpact = total > 0 ? impactSum / total : 0;
  const avgReliability = reliabilityCount > 0 ? reliabilitySum / reliabilityCount : null;
  const densityTarget = timeRange === '24h' ? 8 : timeRange === '7d' ? 16 : 28;
  const density = clamp(total / densityTarget, 0, 1);
  const highImpactShare = total > 0 ? highImpactCount / total : 0;
  const heatScore = Math.round(
    (density * 0.36 + avgImpact * 0.32 + highImpactShare * 0.2 + (avgReliability ?? 0.6) * 0.12) * 100,
  );
  const timeline = buildTimeline(news, timeRange);
  const trend = resolveTrend(timeline);

  let biasLabel = '中性';
  if (score >= 12) biasLabel = '偏多';
  else if (score <= -12) biasLabel = '偏空';

  let heatLabel = '低热';
  if (heatScore >= 75) heatLabel = '高热';
  else if (heatScore >= 50) heatLabel = '升温';
  else if (heatScore >= 30) heatLabel = '温和';

  return {
    total,
    bullish,
    neutral,
    bearish,
    bullishPct: toPct(bullish, total),
    neutralPct: toPct(neutral, total),
    bearishPct: toPct(bearish, total),
    score,
    biasLabel,
    heatScore,
    heatLabel,
    highImpactCount,
    avgReliability,
    trendDirection: trend.direction,
    trendLabel: trend.label,
    trendDelta: trend.delta,
    timeline,
    catalysts: buildCatalysts(news),
  };
};

const trendIcon = (direction: TrendDirection) => {
  if (direction === 'up') return <TrendingUp size={16} />;
  if (direction === 'down') return <TrendingDown size={16} />;
  return <Minus size={16} />;
};

const trendTone = (direction: TrendDirection): string => {
  if (direction === 'up') return 'text-fin-success';
  if (direction === 'down') return 'text-fin-danger';
  return 'text-fin-muted';
};

function DistributionChart({ stats, theme }: { stats: SentimentOverviewStats; theme: ChartTheme }) {
  const option = useMemo(() => ({
    tooltip: {
      trigger: 'item',
      backgroundColor: theme.tooltipBackground,
      borderColor: theme.tooltipBorder,
      textStyle: { color: theme.tooltipText, fontSize: 11 },
      formatter: (params: { name?: string; value?: number; percent?: number }) =>
        `${params.name ?? ''}: ${params.value ?? 0} (${Math.round(params.percent ?? 0)}%)`,
    },
    legend: {
      bottom: 0,
      itemWidth: 10,
      itemHeight: 10,
      textStyle: { color: theme.muted, fontSize: 10 },
    },
    series: [
      {
        name: '情绪分布',
        type: 'pie',
        radius: ['48%', '72%'],
        center: ['50%', '42%'],
        avoidLabelOverlap: true,
        label: {
          color: theme.textSecondary,
          fontSize: 10,
          formatter: '{b} {d}%',
        },
        labelLine: { length: 8, length2: 6 },
        data: [
          { name: '看多', value: stats.bullish, itemStyle: { color: theme.success } },
          { name: '中性', value: stats.neutral, itemStyle: { color: theme.muted } },
          { name: '看空', value: stats.bearish, itemStyle: { color: theme.danger } },
        ],
      },
    ],
  }), [stats.bearish, stats.bullish, stats.neutral, theme]);

  if (stats.total === 0) {
    return <div className="flex h-44 items-center justify-center text-sm text-fin-muted">暂无舆情分布</div>;
  }

  return (
    <ReactECharts
      option={option}
      style={{ width: '100%', height: 210 }}
      opts={{ renderer: 'svg' }}
      notMerge
      lazyUpdate
    />
  );
}

function TimelineChart({ stats, theme }: { stats: SentimentOverviewStats; theme: ChartTheme }) {
  const option = useMemo(() => ({
    tooltip: {
      trigger: 'axis',
      backgroundColor: theme.tooltipBackground,
      borderColor: theme.tooltipBorder,
      textStyle: { color: theme.tooltipText, fontSize: 11 },
      formatter: (params: Array<{ name: string; value: number }>) => {
        const point = params[0];
        if (!point) return '';
        return `${point.name}<br/>情绪分: ${formatSignedScore(point.value)}`;
      },
    },
    grid: { left: 42, right: 16, top: 18, bottom: 30 },
    xAxis: {
      type: 'category' as const,
      data: stats.timeline.map((item) => item.label),
      axisLine: { lineStyle: { color: theme.border } },
      axisLabel: { color: theme.muted, fontSize: 10 },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value' as const,
      min: -100,
      max: 100,
      axisLabel: {
        color: theme.muted,
        fontSize: 10,
        formatter: (value: number) => formatSignedScore(value),
      },
      splitLine: { lineStyle: { color: theme.grid, type: 'dashed' } },
    },
    series: [
      {
        name: '情绪分',
        type: 'line',
        data: stats.timeline.map((item) => item.score),
        smooth: true,
        showSymbol: true,
        symbolSize: 6,
        lineStyle: { color: theme.primary, width: 2 },
        itemStyle: { color: theme.primary },
        areaStyle: { color: theme.primaryFaint },
        markLine: {
          silent: true,
          symbol: 'none',
          lineStyle: { color: theme.border, type: 'dashed' },
          label: { color: theme.muted, fontSize: 10, formatter: '中性' },
          data: [{ yAxis: 0 }],
        },
      },
    ],
  }), [stats.timeline, theme]);

  if (stats.timeline.length === 0) {
    return <div className="flex h-44 items-center justify-center text-sm text-fin-muted">暂无情绪时间线</div>;
  }

  return (
    <ReactECharts
      option={option}
      style={{ width: '100%', height: 210 }}
      opts={{ renderer: 'svg' }}
      notMerge
      lazyUpdate
    />
  );
}

export function NewsSentimentOverview({ news, timeRange, ticker }: NewsSentimentOverviewProps) {
  const theme = useChartTheme();
  const stats = useMemo(() => computeOverviewStats(news, timeRange), [news, timeRange]);
  const scoreTone =
    stats.score > 10 ? 'text-fin-success' : stats.score < -10 ? 'text-fin-danger' : 'text-fin-muted';

  return (
    <section className="space-y-3">
      <div className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-fin-text">
            <RadioTower size={16} className="text-fin-primary" />
            <span>舆情总览</span>
            {ticker && <span className="text-xs font-medium text-fin-muted">{ticker}</span>}
          </div>
          <p className="text-xs text-fin-muted">
            {TIME_RANGE_LABELS[timeRange]} · 基于 Dashboard 新闻列表客户端聚合
          </p>
        </div>
        <div className="text-xs text-fin-muted">
          样本 {stats.total} 条 · 高影响 {stats.highImpactCount} 条
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <div className="rounded-lg border border-fin-border bg-fin-card p-3">
          <div className="text-xs text-fin-muted">整体情绪</div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className={`text-2xl font-semibold ${scoreTone}`}>{formatSignedScore(stats.score)}</span>
            <span className="text-sm font-medium text-fin-text">{stats.biasLabel}</span>
          </div>
          <div className="mt-2 text-2xs text-fin-muted">加权分 -100 到 +100</div>
        </div>

        <div className="rounded-lg border border-fin-border bg-fin-card p-3">
          <div className="flex items-center justify-between text-xs text-fin-muted">
            <span>情绪趋势</span>
            <span className={trendTone(stats.trendDirection)}>{trendIcon(stats.trendDirection)}</span>
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className={`text-xl font-semibold ${trendTone(stats.trendDirection)}`}>{stats.trendLabel}</span>
            {stats.trendDelta != null && (
              <span className="text-xs text-fin-muted">{formatSignedScore(stats.trendDelta)}</span>
            )}
          </div>
          {/* TODO: 后端 dashboard.news 接入 NewsSentimentSnapshot.sentiment_trend 后，用后端趋势替换客户端时间线估算。 */}
          <div className="mt-2 text-2xs text-fin-muted">客户端时间线估算</div>
        </div>

        <div className="rounded-lg border border-fin-border bg-fin-card p-3">
          <div className="flex items-center justify-between text-xs text-fin-muted">
            <span>舆情热度</span>
            <Flame size={15} className="text-fin-warning" />
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-semibold text-fin-text">{stats.heatScore}</span>
            <span className="text-sm font-medium text-fin-warning">{stats.heatLabel}</span>
          </div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-fin-border">
            <div
              className="h-full rounded-full bg-fin-warning transition-all duration-500"
              style={{ width: `${stats.heatScore}%` }}
            />
          </div>
        </div>

        <div className="rounded-lg border border-fin-border bg-fin-card p-3">
          <div className="flex items-center justify-between text-xs text-fin-muted">
            <span>信源质量</span>
            <Activity size={15} className="text-fin-primary" />
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-semibold text-fin-text">
              {stats.avgReliability == null ? '--' : `${Math.round(stats.avgReliability * 100)}%`}
            </span>
            <span className="text-xs text-fin-muted">平均可靠性</span>
          </div>
          <div className="mt-2 grid grid-cols-3 gap-1 text-2xs">
            <span className="text-fin-success">多 {stats.bullishPct}%</span>
            <span className="text-fin-muted">中 {stats.neutralPct}%</span>
            <span className="text-fin-danger">空 {stats.bearishPct}%</span>
          </div>
        </div>
      </div>

      <div className="grid gap-3 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <div className="rounded-lg border border-fin-border bg-fin-card p-3">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-fin-text">情绪分布</h3>
            <span className="text-2xs text-fin-muted">看多 / 中性 / 看空</span>
          </div>
          <DistributionChart stats={stats} theme={theme} />
        </div>

        <div className="rounded-lg border border-fin-border bg-fin-card p-3">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-fin-text">情绪时间线</h3>
            <span className="text-2xs text-fin-muted">客户端聚合情绪分</span>
          </div>
          <TimelineChart stats={stats} theme={theme} />
        </div>
      </div>

      <div className="grid gap-3 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
        <div className="rounded-lg border border-fin-border bg-fin-card p-3">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-fin-text">催化事件时间线</h3>
            <span className="text-2xs text-fin-muted">来自高影响新闻</span>
          </div>
          {/* TODO: 后端 dashboard.news 接入 NewsSentimentSnapshot.catalyst_events 后，优先展示后端聚合催化事件。 */}
          {stats.catalysts.length === 0 ? (
            <div className="flex h-24 items-center justify-center text-sm text-fin-muted">
              暂无高影响催化事件
            </div>
          ) : (
            <div className="space-y-3">
              {stats.catalysts.map((event) => (
                <div key={event.id} className="flex gap-3">
                  <div className="flex flex-col items-center">
                    <span className={`mt-1 h-2.5 w-2.5 rounded-full ${SENTIMENT_DOT[event.sentiment]}`} />
                    <span className="mt-1 h-full w-px bg-fin-border" />
                  </div>
                  <div className="min-w-0 flex-1 pb-1">
                    <div className="flex flex-wrap items-center gap-2 text-2xs text-fin-muted">
                      <span>{formatNewsTime(event.ts)}</span>
                      {event.source && <span>{event.source}</span>}
                      <span className={SENTIMENT_TONE[event.sentiment]}>
                        {SENTIMENT_LABELS[event.sentiment]}
                      </span>
                      <span>影响 {Math.round(event.impactScore * 100)}%</span>
                    </div>
                    <p className="mt-1 line-clamp-2 text-sm font-medium text-fin-text">{event.title}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="rounded-lg border border-dashed border-fin-border bg-fin-card p-3">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-fin-text">舆情-价格传导</h3>
            <span className="text-2xs text-fin-muted">待接入</span>
          </div>
          <p className="text-sm leading-6 text-fin-muted">
            Dashboard REST 尚未暴露 NewsSentimentSnapshot.price_transmission，
            当前不推断价格共振、背离或传导强度。
          </p>
          <div className="mt-3 rounded-lg bg-fin-hover/40 p-3 text-xs text-fin-muted">
            {/* TODO: 后端 dashboard.news 接入 NewsSentimentSnapshot.price_transmission 后，在此展示共振/背离、价格窗口和置信度。 */}
            需要后端把 NewsAgent 聚合快照同步进 /api/dashboard。
          </div>
        </div>
      </div>
    </section>
  );
}

export default NewsSentimentOverview;
