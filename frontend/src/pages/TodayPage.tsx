import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  ArrowRight,
  CircleAlert,
  Clock3,
  MessageCircleQuestion,
  RefreshCw,
  TrendingDown,
  TrendingUp,
  WalletCards,
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';

import { apiClient, type MarketDataResponse, type QuoteData } from '../api/client';
import type { PredictionHistoryItem } from '../api/domains/predictions';
import { usePredictionHistory } from '../hooks/usePredictionHistory';
import { useStore } from '../store/useStore';
import { useDashboardStore } from '../store/dashboardStore';
import type { WatchItem } from '../types/dashboard';

type QuoteState = {
  price?: number;
  changePct?: number;
  source?: string | null;
  asOf?: string | null;
  quality?: MarketDataResponse<QuoteData>['data']['quality'];
  cached?: boolean;
  status: 'loading' | 'ready' | 'unavailable';
};

const OUTCOME_LABELS: Record<string, string> = {
  waiting: '等待验证',
  open: '观察中',
  triggered: '验证条件已出现',
  invalidated: '研究判断不再成立',
  hit_target: '假设目标成立',
  hit_stop: '风险边界触发',
  held_range: '区间假设成立',
  broke_range: '区间假设失效',
  data_pending: '等待公开行情',
};

const DIRECTION_LABELS = {
  long: '偏多观点',
  short: '偏空观点',
  neutral: '中性观点',
} as const;

function formatDateTime(value: string | null | undefined): string {
  if (!value) return '未提供';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

function formatPrice(value: number | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '不可用';
  return value.toFixed(2);
}

function formatPercent(value: number | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '不可用';
  const sign = value >= 0 ? '+' : '';
  return `${sign}${value.toFixed(2)}%`;
}

function formatHitRate(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '未提供';
  const percentage = Math.abs(value) <= 1 ? value * 100 : value;
  return `${percentage.toFixed(1)}%`;
}

function normalizeQuote(payload: MarketDataResponse<QuoteData>): Omit<QuoteState, 'status'> {
  const envelope = payload.data;
  const quote = envelope.data;
  const price = Number(quote?.price);
  const changePct = Number(quote?.change_percent);
  return {
    price: Number.isFinite(price) ? price : undefined,
    changePct: Number.isFinite(changePct) ? changePct : undefined,
    source: envelope.provider || envelope.source,
    asOf: envelope.as_of,
    quality: envelope.quality,
    cached: envelope.cached || payload.cached === true,
  };
}

async function loadWatchlistQuotes(
  watchlist: WatchItem[],
  signal: AbortSignal,
): Promise<Record<string, QuoteState>> {
  const entries = await Promise.all(watchlist.map(async (item) => {
    try {
      const response = await apiClient.fetchStockPrice(item.symbol, signal);
      const normalized = normalizeQuote(response);
      return [item.symbol, {
        ...normalized,
        status: normalized.price === undefined ? 'unavailable' : 'ready',
      } satisfies QuoteState] as const;
    } catch (reason) {
      if (signal.aborted) throw reason;
      return [item.symbol, { status: 'unavailable' } satisfies QuoteState] as const;
    }
  }));
  return Object.fromEntries(entries);
}

function getStatusBadgeTone(status: string): string {
  if (['hit_target', 'held_range'].includes(status)) {
    return 'border-t-up/40 bg-t-up/10 text-t-up';
  }
  if (['hit_stop', 'invalidated', 'broke_range'].includes(status)) {
    return 'border-t-down/40 bg-t-down/10 text-t-down';
  }
  return 'border-t-border bg-t-hover text-t-text2';
}

function getQuoteStatusLabel(quote: QuoteState | undefined): string {
  if (!quote || quote.status === 'loading') return '读取中';
  if (quote.status !== 'ready') return '不可用';
  if (!quote.source || !quote.asOf) return '信息不完整';
  if (quote.quality === 'degraded') return '降级数据';
  return quote.cached ? '缓存数据' : '可信数据';
}

function getDirectionTone(direction: PredictionHistoryItem['prediction']['direction']): string {
  if (direction === 'long') return 'text-t-up';
  if (direction === 'short') return 'text-t-down';
  return 'text-t-text2';
}

function StatusBadge({ status }: { status: string }) {
  const label = OUTCOME_LABELS[status] || status || '未提供';
  const tone = getStatusBadgeTone(status);
  return <span className={`rounded border px-1.5 py-0.5 text-2xs ${tone}`}>{label}</span>;
}

function QuoteCard({
  item,
  quote,
  onOpen,
}: {
  item: WatchItem;
  quote?: QuoteState;
  onOpen: () => void;
}) {
  const isLoading = !quote || quote.status === 'loading';
  const hasPrice = quote?.status === 'ready';
  const isUp = (quote?.changePct ?? 0) >= 0;
  const statusLabel = getQuoteStatusLabel(quote);
  return (
    <button
      type="button"
      onClick={onOpen}
      className="group min-h-[142px] rounded-xl border border-t-border bg-t-surface p-4 text-left transition-colors hover:border-t-accent/50 hover:bg-t-hover"
      data-testid="today-watchlist-card"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="font-mono text-sm font-semibold text-t-text">{item.symbol}</div>
          <div className="mt-1 truncate text-xs text-t-text3">{item.name || item.symbol}</div>
        </div>
        <ArrowRight size={15} className="shrink-0 text-t-text3 transition-transform group-hover:translate-x-0.5 group-hover:text-t-accent" />
      </div>
      <div className="mt-5 flex items-end justify-between gap-2">
        <div>
          <div className="font-mono text-xl font-semibold tabular-nums text-t-text">{isLoading ? '读取中...' : formatPrice(quote?.price)}</div>
          <div className={`mt-1 text-xs ${hasPrice ? (isUp ? 'text-t-up' : 'text-t-down') : 'text-t-text3'}`}>
            {isLoading ? '等待行情' : hasPrice ? formatPercent(quote?.changePct) : '行情不可用'}
          </div>
        </div>
        <div className="text-right text-2xs leading-5 text-t-text3">
          <div>状态：{statusLabel}</div>
          <div>来源：{quote?.source || '未提供'}</div>
          <div>截至：{formatDateTime(quote?.asOf)}</div>
        </div>
      </div>
    </button>
  );
}

function PredictionCard({ item, onDashboard, onAsk, onHistory }: {
  item: PredictionHistoryItem;
  onDashboard: () => void;
  onAsk: () => void;
  onHistory: () => void;
}) {
  const prediction = item.prediction;
  const outcome = item.outcome;
  const status = outcome?.status || prediction.status;
  const directionTone = getDirectionTone(prediction.direction);
  return (
    <article className="rounded-xl border border-t-border bg-t-surface p-4" data-testid="today-prediction-card">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <span className="font-mono text-sm font-semibold text-t-text">{prediction.symbol}</span>
          <span className={`inline-flex items-center gap-1 text-xs font-medium ${directionTone}`}>
            {prediction.direction === 'short' ? <TrendingDown size={13} /> : <TrendingUp size={13} />}
            {DIRECTION_LABELS[prediction.direction]}
          </span>
          <StatusBadge status={status} />
        </div>
        <span className="inline-flex items-center gap-1 text-2xs text-t-text3">
          <Clock3 size={12} /> {formatDateTime(prediction.created_at)}
        </span>
      </div>
      <p className="mt-3 text-sm leading-6 text-t-text2">{prediction.thesis || '这条研究判断没有提供文字依据。'}</p>
      <div className="mt-3 grid gap-2 border-t border-t-border pt-3 text-2xs text-t-text3 sm:grid-cols-3">
        <div>来源：{prediction.source_type === 'ai' ? 'AI 研究判断' : '人工研究记录'}</div>
        <div>证据：{prediction.evidence_provider || '未提供'}</div>
        <div>数据截至：{formatDateTime(prediction.evidence_as_of)}</div>
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        <button type="button" onClick={onDashboard} className="inline-flex min-h-9 items-center gap-1.5 rounded-md border border-t-border px-3 text-xs text-t-text2 hover:border-t-accent/50 hover:text-t-text">
          打开看板 <ArrowRight size={13} />
        </button>
        <button type="button" onClick={onAsk} className="inline-flex min-h-9 items-center gap-1.5 rounded-md border border-t-accent/40 bg-t-accent/10 px-3 text-xs text-t-accent hover:bg-t-accent/15">
          <MessageCircleQuestion size={13} /> 继续追问
        </button>
        <button type="button" onClick={onHistory} className="min-h-9 rounded-md px-2 text-xs text-t-text3 hover:text-t-text">查看历史</button>
      </div>
    </article>
  );
}

export function TodayPage() {
  const navigate = useNavigate();
  const authIdentity = useStore((state) => state.authIdentity);
  const entryMode = useStore((state) => state.entryMode);
  const setWatchlist = useDashboardStore((state) => state.setWatchlist);
  const [updatedAt, setUpdatedAt] = useState(() => new Date());
  const watchlistQuery = useQuery({
    queryKey: ['watchlist', authIdentity?.userId || 'anonymous'],
    queryFn: ({ signal }) => apiClient.getWatchlist(signal),
    enabled: Boolean(authIdentity?.userId),
    staleTime: 30_000,
  });
  const watchlist = useMemo<WatchItem[]>(
    () => (watchlistQuery.data?.items ?? []).map((item) => ({
      symbol: item.ticker.trim().toUpperCase(),
      type: 'equity',
      name: item.note || item.ticker.trim().toUpperCase(),
    })),
    [watchlistQuery.data?.items],
  );
  const quoteSymbols = useMemo(() => watchlist.map((item) => item.symbol), [watchlist]);
  const quoteQuery = useQuery({
    queryKey: ['today-watchlist-quotes', quoteSymbols],
    queryFn: ({ signal }) => loadWatchlistQuotes(watchlist, signal),
    enabled: Boolean(authIdentity?.userId) && watchlistQuery.isSuccess && watchlist.length > 0,
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
  const quotes = quoteQuery.data ?? {};
  const quotesLoading = watchlistQuery.isFetching || quoteQuery.isFetching;
  const allQuotesUnavailable = watchlist.length > 0
    && Boolean(quoteQuery.data)
    && watchlist.every((item) => quotes[item.symbol]?.status === 'unavailable');
  const quotesError = quoteQuery.error instanceof Error
    ? quoteQuery.error.message
    : allQuotesUnavailable ? '自选报价暂时不可用，稍后可重试。' : null;
  const watchlistError = watchlistQuery.error instanceof Error
    ? watchlistQuery.error.message
    : watchlistQuery.isError ? '自选列表读取失败，请稍后重试。' : null;
  const {
    items: predictionItems,
    stats,
    loading: predictionsLoading,
    failure: predictionsFailure,
    refresh: refreshPredictions,
  } = usePredictionHistory({ enabled: Boolean(authIdentity?.userId), limit: 100 });

  useEffect(() => {
    if (watchlistQuery.isSuccess) setWatchlist(watchlist);
  }, [setWatchlist, watchlist, watchlistQuery.isSuccess]);

  const recentPredictions = useMemo(
    () => [...predictionItems]
      .sort((a, b) => Date.parse(b.prediction.created_at) - Date.parse(a.prediction.created_at))
      .slice(0, 5),
    [predictionItems],
  );
  const followUps = useMemo(
    () => recentPredictions.filter(({ prediction, outcome }) => {
      const status = outcome?.status || prediction.status;
      return ['waiting', 'open', 'triggered', 'data_pending'].includes(status);
    }).slice(0, 3),
    [recentPredictions],
  );

  const refresh = () => {
    void watchlistQuery.refetch();
    void quoteQuery.refetch();
    refreshPredictions();
    setUpdatedAt(new Date());
  };

  if (!authIdentity?.userId) {
    return (
      <main className="mx-auto flex min-h-full max-w-3xl items-center justify-center" data-testid="today-page">
        <section className="w-full rounded-xl border border-t-border bg-t-surface p-6 sm:p-8">
          <div className="flex items-start gap-3">
            <CircleAlert className="mt-0.5 shrink-0 text-t-warning" size={20} />
            <div>
              <h1 className="text-xl font-semibold text-t-text">登录后查看你的今日摘要</h1>
              <p className="mt-2 text-sm leading-6 text-t-text2">
                自选标的、研究判断和待复盘内容属于个人数据。当前以只读访客模式浏览，系统不会猜测或展示其他人的内容。
              </p>
              <div className="mt-5 flex flex-wrap gap-2">
                <button type="button" onClick={() => navigate('/welcome?from=/today')} className="inline-flex min-h-10 items-center gap-1.5 rounded-md bg-t-accent px-4 text-sm font-medium text-white hover:bg-t-accent-hi">
                  登录并同步自选 <ArrowRight size={14} />
                </button>
                <button type="button" onClick={() => navigate('/dashboard')} className="inline-flex min-h-10 items-center gap-1.5 rounded-md border border-t-border px-4 text-sm text-t-text2 hover:border-t-accent/50 hover:text-t-text">
                  浏览只读行情
                </button>
              </div>
              <p className="mt-4 text-2xs text-t-text3">当前入口：{entryMode === 'anonymous' ? '只读访客' : '等待身份确认'}</p>
            </div>
          </div>
        </section>
      </main>
    );
  }

  return (
    <main className="min-h-full" data-testid="today-page">
      <header className="flex flex-wrap items-end justify-between gap-4 border-b border-t-border pb-5">
        <div>
          <div className="flex items-center gap-2">
            <WalletCards size={19} className="text-t-accent" />
            <h1 className="text-xl font-semibold text-t-text">今日</h1>
          </div>
          <p className="mt-2 text-sm text-t-text2">先看关注标的的变化，再决定要不要继续研究。</p>
          <p className="mt-1 text-2xs text-t-text3">页面查看于 {formatDateTime(updatedAt.toISOString())} · 所有数据保留来源和数据时点</p>
        </div>
        <button type="button" onClick={refresh} disabled={quotesLoading || predictionsLoading} className="inline-flex min-h-10 items-center gap-1.5 rounded-md border border-t-border px-3 text-xs text-t-text2 hover:border-t-accent/50 hover:text-t-text disabled:opacity-50" data-testid="today-refresh">
          <RefreshCw size={14} className={quotesLoading || predictionsLoading ? 'animate-spin' : ''} /> 刷新
        </button>
      </header>

      <section className="mt-5" aria-labelledby="today-watchlist-title">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 id="today-watchlist-title" className="text-sm font-semibold text-t-text">自选标的变化</h2>
            <p className="mt-1 text-xs text-t-text3">只显示接口返回的真实报价；缺失时明确标记。</p>
          </div>
          <button type="button" onClick={() => navigate('/dashboard')} className="text-xs text-t-accent hover:underline">管理自选</button>
        </div>
        {quotesError ? (
          <div className="mt-3 flex items-center justify-between gap-3 rounded-lg border border-t-warning/40 bg-t-warning/10 px-3 py-2 text-xs text-t-warning" data-testid="today-quotes-error">
            <span>{quotesError}</span>
            <button type="button" onClick={() => void quoteQuery.refetch()} className="inline-flex items-center gap-1"><RefreshCw size={12} />重试</button>
          </div>
        ) : null}
        {watchlistError ? (
          <div className="mt-3 flex items-center justify-between gap-3 rounded-lg border border-t-down/35 bg-t-down/10 px-3 py-3 text-xs text-t-down" data-testid="today-watchlist-error">
            <span>{watchlistError}</span>
            <button type="button" onClick={() => void watchlistQuery.refetch()} className="inline-flex items-center gap-1"><RefreshCw size={12} />重试</button>
          </div>
        ) : watchlistQuery.isPending ? (
          <div className="mt-3 flex min-h-32 items-center justify-center gap-2 rounded-xl border border-t-border bg-t-surface text-xs text-t-text3" data-testid="today-watchlist-loading"><RefreshCw size={14} className="animate-spin" />读取自选列表...</div>
        ) : watchlist.length === 0 ? (
          <div className="mt-3 rounded-xl border border-dashed border-t-border bg-t-surface px-5 py-8 text-center" data-testid="today-watchlist-empty">
            <p className="text-sm text-t-text2">还没有自选标的</p>
            <p className="mt-1 text-xs text-t-text3">在看板中添加一只股票，下一次打开这里就能看到变化。</p>
            <button type="button" onClick={() => navigate('/dashboard')} className="mt-4 inline-flex min-h-9 items-center gap-1.5 rounded-md border border-t-accent/40 bg-t-accent/10 px-3 text-xs text-t-accent">去添加自选 <ArrowRight size={13} /></button>
          </div>
        ) : (
          <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {watchlist.map((item) => (
              <QuoteCard key={item.symbol} item={item} quote={quotes[item.symbol]} onOpen={() => navigate(`/dashboard/${encodeURIComponent(item.symbol)}`)} />
            ))}
          </div>
        )}
      </section>

      <section className="mt-8 grid gap-6 xl:grid-cols-[minmax(0,1.5fr)_minmax(280px,0.8fr)]">
        <div>
          <div className="flex items-end justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-t-text">研究判断 / 复盘结果</h2>
              <p className="mt-1 text-xs text-t-text3">这些内容用于跟踪和复盘，不构成投资建议或执行指令。</p>
            </div>
            <button type="button" onClick={() => navigate('/history')} className="text-xs text-t-accent hover:underline">查看全部</button>
          </div>
          {predictionsFailure ? (
            <div className="mt-3 rounded-lg border border-t-down/35 bg-t-down/10 px-3 py-3 text-xs text-t-down" data-testid="today-predictions-error">
              <div className="flex items-center justify-between gap-3"><span>{predictionsFailure.message}</span><button type="button" onClick={refreshPredictions} className="inline-flex items-center gap-1"><RefreshCw size={12} />重试</button></div>
            </div>
          ) : predictionsLoading ? (
            <div className="mt-3 flex min-h-32 items-center justify-center gap-2 rounded-xl border border-t-border bg-t-surface text-xs text-t-text3" data-testid="today-predictions-loading"><RefreshCw size={14} className="animate-spin" />读取最近研究判断...</div>
          ) : recentPredictions.length === 0 ? (
            <div className="mt-3 rounded-xl border border-dashed border-t-border bg-t-surface px-5 py-8 text-center" data-testid="today-predictions-empty">
              <p className="text-sm text-t-text2">还没有待复盘的研究判断</p>
              <p className="mt-1 text-xs text-t-text3">可以先在对话中提出一个具体问题，再回到这里记录证据变化。</p>
              <button type="button" onClick={() => navigate('/chat')} className="mt-4 inline-flex min-h-9 items-center gap-1.5 rounded-md bg-t-accent px-3 text-xs text-white">开始提问 <ArrowRight size={13} /></button>
            </div>
          ) : (
            <div className="mt-3 space-y-3">{recentPredictions.map((item) => <PredictionCard key={item.prediction.prediction_id} item={item} onDashboard={() => navigate(`/dashboard/${encodeURIComponent(item.prediction.symbol)}?analysis=prediction&predictionId=${encodeURIComponent(item.prediction.prediction_id)}`)} onAsk={() => navigate(`/chat?prompt=${encodeURIComponent(`请复盘 ${item.prediction.symbol} 这条研究判断，说明最新公开证据、反方证据和失效条件`)}&context_symbol=${encodeURIComponent(item.prediction.symbol)}`)} onHistory={() => navigate('/history')} />)}</div>
          )}
        </div>

        <aside className="min-w-0">
          <div className="flex items-end justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-t-text">待追问</h2>
              <p className="mt-1 text-xs text-t-text3">这些研究判断还没有最终复盘，适合补一轮公开证据。</p>
            </div>
            <MessageCircleQuestion size={16} className="text-t-accent" />
          </div>
          <div className="mt-3 rounded-xl border border-t-border bg-t-surface p-4">
            {followUps.length === 0 ? (
              <div className="py-5 text-center text-xs text-t-text3" data-testid="today-followups-empty">当前没有待追问项。<button type="button" onClick={() => navigate('/chat')} className="ml-1 text-t-accent hover:underline">去提一个问题</button></div>
            ) : (
              <div className="space-y-3" data-testid="today-followups">
                {followUps.map(({ prediction, outcome }) => {
                  const status = outcome?.status || prediction.status;
                  return (
                    <button key={prediction.prediction_id} type="button" onClick={() => navigate(`/chat?prompt=${encodeURIComponent(`请复盘 ${prediction.symbol} 的${DIRECTION_LABELS[prediction.direction]}研究判断，说明最新公开证据、反方证据和失效条件`)}&context_symbol=${encodeURIComponent(prediction.symbol)}`)} className="w-full border-b border-t-border pb-3 text-left last:border-b-0 last:pb-0 hover:text-t-accent" data-testid="today-followup-item">
                      <div className="flex items-center justify-between gap-2"><span className="font-mono text-xs font-semibold text-t-text">{prediction.symbol}</span><StatusBadge status={status} /></div>
                      <div className="mt-1 line-clamp-2 text-xs leading-5 text-t-text2">复盘这条研究判断是否仍有足够依据</div>
                      <div className="mt-1 text-2xs text-t-text3">证据截至 {formatDateTime(prediction.evidence_as_of)}</div>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
          {stats ? <div className="mt-3 border-t border-t-border pt-3 text-2xs text-t-text3">最近 90 天：{stats.predictions} 条研究判断 · {stats.resolved} 条已复盘 · 历史命中率 {formatHitRate(stats.hit_rate)}</div> : null}
        </aside>
      </section>
    </main>
  );
}

export default TodayPage;
