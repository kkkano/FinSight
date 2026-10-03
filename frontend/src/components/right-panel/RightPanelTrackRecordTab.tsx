import { useEffect, useRef, useState } from 'react';
import { ArrowLeft, ChevronLeft, ChevronRight, LogIn, RefreshCw, Target } from 'lucide-react';
import { Link, useLocation } from 'react-router-dom';
import { apiClient } from '../../api/client';
import { toPredictionFailure, type PredictionFailure, type PredictionHistoryItem, type PredictionStatBucket, type PredictionStatsResponse } from '../../api/domains/predictions';
import { usePredictionRunState } from '../../hooks/usePredictionHistory';
import { useStore } from '../../store/useStore';
import { formatPercentagePoints, formatRatioPercent } from '../../pages/historyFormatting';
import { getPredictionDirectionPresentation, isTerminalPredictionStatus } from '../../utils/predictionPresentation';
import { BenchmarkTrackRecordView } from '../track-record/BenchmarkTrackRecord';
import { PERSONAL_OUTCOME_LABELS, PERSONAL_PAGE_SIZE, formatPersonalPrice, formatPersonalTime, loadPersonalPredictionPage } from './personalTrackRecord';

type TrackRecordView = 'personal' | 'us20';
type DirectionFilter = 'long' | 'short' | 'neutral' | '';
const controlClass = 'min-h-10 rounded-md border border-t-border bg-t-surface px-3 text-sm text-t-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-t-accent disabled:opacity-40';

function Stats({ stats }: { stats: PredictionStatBucket | null }) {
  return <dl className="grid grid-cols-2 gap-x-5 gap-y-4 border-b border-t-divider py-5" aria-label="90 天我的判断统计">
    {[
      ['AI 判断', stats ? String(stats.predictions) : '--'],
      ['已结算', stats ? String(stats.resolved) : '--'],
      ['命中率', stats && stats.resolved > 0 ? formatRatioPercent(stats.hit_rate) : '--'],
      ['已失效', stats ? String(stats.invalidated) : '--'],
    ].map(([label, value]) => <div key={label} className="min-w-0"><dt className="text-xs text-t-text3">{label}</dt><dd className="mt-1 text-xl font-semibold tabular-nums text-t-text">{value}</dd></div>)}
    <div className="col-span-2"><dt className="sr-only">样本范围</dt><dd className="text-xs leading-5 text-t-text3">{stats ? stats.resolved > 0 ? `${stats.hits} 命中 · ${stats.misses} 未命中` : '暂无已结算样本，命中率保留为空。' : '统计尚未读取，命中率保留为空。'}仅统计最近 90 天的 AI 判断，与 US20 固定样本独立。</dd></div>
  </dl>;
}

export function PersonalPredictionDetail({ item }: { item: PredictionHistoryItem }) {
  const { prediction, outcome } = item;
  const { run, loading, failure, refresh } = usePredictionRunState(prediction.run_id);
  const status = outcome?.status || prediction.status;
  const direction = getPredictionDirectionPresentation(prediction.direction, status);
  const ended = isTerminalPredictionStatus(status);
  return <article className="min-w-0" data-testid="personal-record-detail">
    <div className="flex flex-wrap items-start justify-between gap-2">
      <h3 className="text-lg font-semibold text-t-text">{prediction.symbol}</h3>
      <span className="text-xs leading-5 text-t-text2">{ended ? '历史判断 · ' : ''}{PERSONAL_OUTCOME_LABELS[status] || status}</span>
    </div>
    <p className="mt-2 text-sm font-medium text-t-text">{prediction.source_type === 'manual' ? direction.label.replace(/^AI /, '手动 ') : direction.label}</p>
    <p className="mt-1 text-xs leading-5 text-t-text3">{direction.description}</p>
    <p className="mt-3 text-xs leading-5 text-t-text3">生成于 {formatPersonalTime(prediction.created_at)} · {prediction.anchor.timeframe === '1d' ? '日线证据' : prediction.anchor.timeframe}</p>
    <p className="mt-1 text-xs leading-5 text-t-text3">有效范围为所列入场、目标与失效条件，未定义固定持有天数。</p>
    {ended ? <p className="mt-3 text-sm leading-6 text-t-text2">这条判断已结束，保留原结论用于复盘，不代表当前观点。</p> : null}
    <section className="mt-5 border-t border-t-divider py-5">
      <h4 className="text-sm font-semibold text-t-text">原判断与价格条件</h4>
      <p className="mt-3 break-words text-sm leading-6 text-t-text2">{prediction.thesis}</p>
      <dl className="mt-4 grid grid-cols-2 gap-x-5 gap-y-4">
        {[
          ['锚点', prediction.anchor.price], ['入场', prediction.entry], ['止损', prediction.stop],
          ['目标 1', prediction.target1], ['目标 2', prediction.target2], ['失效价', prediction.invalidation_price],
        ].map(([label, value]) => <div key={label} className="min-w-0"><dt className="text-xs text-t-text3">{label}</dt><dd className="mt-1 text-base font-medium tabular-nums text-t-text">{formatPersonalPrice(value as number | null | undefined)}</dd></div>)}
      </dl>
      {prediction.range ? <p className="mt-4 text-sm text-t-text2">判断区间：{formatPersonalPrice(prediction.range.low)} – {formatPersonalPrice(prediction.range.high)}</p> : null}
    </section>
    <section className="border-t border-t-divider py-5">
      <h4 className="text-sm font-semibold text-t-text">实际结果</h4>
      <dl className="mt-3 space-y-3 text-sm">
        <div><dt className="text-xs text-t-text3">状态</dt><dd className="mt-1 text-t-text2">{PERSONAL_OUTCOME_LABELS[status] || status}</dd></div>
        <div><dt className="text-xs text-t-text3">锚点后变动</dt><dd className="mt-1 tabular-nums text-t-text2">{formatPercentagePoints(outcome?.pct_since_anchor)}</dd></div>
        <div><dt className="text-xs text-t-text3">评估至</dt><dd className="mt-1 text-t-text2">{formatPersonalTime(outcome?.evaluated_through)}</dd></div>
        {outcome?.resolved_at ? <div><dt className="text-xs text-t-text3">结束时间</dt><dd className="mt-1 text-t-text2">{formatPersonalTime(outcome.resolved_at)}</dd></div> : null}
        {outcome?.resolution_reason ? <div><dt className="text-xs text-t-text3">结算原因</dt><dd className="mt-1 break-words leading-6 text-t-text2">{outcome.resolution_reason}</dd></div> : null}
      </dl>
      {!outcome || !ended ? <p className="mt-3 text-xs leading-5 text-t-text3">尚未产生最终结果；不会计为命中或未命中。</p> : null}
    </section>
    <section className="border-t border-t-divider py-5">
      <h4 className="text-sm font-semibold text-t-text">生成与模型来源</h4>
      {failure ? <div role="alert" className="mt-3 text-sm leading-6 text-t-down">模型来源暂时无法读取。<button type="button" onClick={refresh} className="ml-2 inline-flex min-h-9 items-center gap-1 underline"><RefreshCw size={14} />重试</button></div> : null}
      <dl className="mt-3 space-y-3 break-words text-sm">
        {[
          ['模型', loading ? '正在读取…' : run?.llm_model || '--'],
          ['供应商', run?.llm_provider || '--'],
          ['证据行情', prediction.evidence_provider || run?.market_provider || '--'],
          ['证据时间', formatPersonalTime(prediction.evidence_as_of || run?.market_as_of)],
          ['提示版本', prediction.prompt_version],
          ['评估版本', outcome?.algorithm_version || '--'],
          ['生成来源', prediction.source_type === 'ai' ? 'AI 判断' : '手动判断'],
        ].map(([label, value]) => <div key={label}><dt className="text-xs text-t-text3">{label}</dt><dd className="mt-1 text-t-text2">{value}</dd></div>)}
      </dl>
      {run?.failure_code ? <p className="mt-3 break-words text-xs leading-5 text-t-down">生成失败：{run.failure_detail || run.failure_code}</p> : null}
    </section>
    {prediction.scenarios.length ? <section className="border-t border-t-divider py-5">
      <h4 className="text-sm font-semibold text-t-text">情景与失效条件</h4>
      <div className="mt-3 space-y-4">{prediction.scenarios.map((scenario) => <div key={`${scenario.name}-${scenario.probability}`} className="text-sm">
        <p className="break-words font-medium text-t-text">{scenario.name} · {formatPercentagePoints(scenario.probability)}</p>
        <p className="mt-1 break-words leading-6 text-t-text2">失效条件：{scenario.invalidation}</p>
      </div>)}</div>
    </section> : null}
  </article>;
}

function PersonalTrackRecordView({ symbol }: { symbol?: string }) {
  const [scope, setScope] = useState<'current' | 'all'>(symbol ? 'current' : 'all');
  const [direction, setDirection] = useState<DirectionFilter>('');
  const [offset, setOffset] = useState(0);
  const [refreshKey, setRefreshKey] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [result, setResult] = useState<{ key: string; offset: number; items: PredictionHistoryItem[]; hasMore: boolean } | null>(null);
  const [stats, setStats] = useState<{ symbol: string | undefined; value: PredictionStatsResponse['stats'] } | null>(null);
  const [loading, setLoading] = useState(true);
  const [failure, setFailure] = useState<PredictionFailure | null>(null);
  const [statsFailure, setStatsFailure] = useState(false);
  const contentRef = useRef<HTMLDivElement>(null);
  const filterSymbol = scope === 'current' ? symbol : undefined;
  const queryKey = JSON.stringify([filterSymbol, direction]);
  const page = result?.key === queryKey ? result : null;
  const selected = page?.items.find((item) => item.prediction.prediction_id === selectedId);
  const scopedStats = stats && stats.symbol === filterSymbol ? stats.value : null;
  const aiStats = scopedStats?.by_source.ai || null;
  const refresh = () => setRefreshKey((value) => value + 1);

  useEffect(() => {
    setOffset(0);
    setSelectedId(null);
  }, [filterSymbol, direction]);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setFailure(null);
    loadPersonalPredictionPage({ symbol: filterSymbol, direction: direction || undefined, offset }, controller.signal).then((response) => {
      if (!controller.signal.aborted) setResult({ key: queryKey, offset, ...response });
    }).catch((error) => {
      if (!controller.signal.aborted) setFailure(toPredictionFailure(error));
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [filterSymbol, direction, offset, queryKey, refreshKey]);
  useEffect(() => {
    const controller = new AbortController();
    setStatsFailure(false);
    apiClient.getPredictionStats({ symbol: filterSymbol, days: 90 }, controller.signal).then((response) => {
      if (!controller.signal.aborted) setStats({ symbol: filterSymbol, value: response.stats });
    }).catch(() => {
      if (!controller.signal.aborted) setStatsFailure(true);
    });
    return () => controller.abort();
  }, [filterSymbol, refreshKey]);
  const selectRecord = (id: string | null) => {
    setSelectedId(id);
    contentRef.current?.scrollIntoView({ block: 'start' });
  };

  return <div ref={contentRef} className="min-w-0" data-testid="personal-track-record">
    <div className="flex flex-wrap items-start justify-between gap-3 pb-4">
      <div><h2 className="text-base font-semibold text-t-text">我的判断</h2><p className="mt-1 text-xs leading-5 text-t-text3">{filterSymbol || '全部标的'} · 仅自己的记录</p></div>
      <button type="button" aria-label="刷新我的判断" title="刷新我的判断" className={controlClass} onClick={refresh} disabled={loading}><RefreshCw size={16} className={loading ? 'animate-spin' : ''} /></button>
    </div>
    {failure ? <div role="alert" className="pb-4 text-sm leading-6 text-t-down">{failure.message}{page ? '保留上次加载的记录。' : ''}</div> : null}
    {selected ? <>
      <button type="button" onClick={() => selectRecord(null)} className="mb-4 inline-flex min-h-10 items-center gap-2 text-sm text-t-text2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-t-accent"><ArrowLeft size={16} />返回我的判断</button>
      <PersonalPredictionDetail key={selected.prediction.prediction_id} item={selected} />
    </> : <>
      <div className="grid grid-cols-2 gap-3">
        <label className="min-w-0 text-xs text-t-text3">标的范围<select aria-label="我的判断标的范围" className={`${controlClass} mt-1 w-full`} value={scope} onChange={(event) => setScope(event.target.value as 'current' | 'all')}><option value="all">全部标的</option><option value="current" disabled={!symbol}>{symbol ? `当前 ${symbol}` : '未选择标的'}</option></select></label>
        <label className="min-w-0 text-xs text-t-text3">原判断方向<select aria-label="我的判断方向筛选" className={`${controlClass} mt-1 w-full`} value={direction} onChange={(event) => setDirection(event.target.value as DirectionFilter)}><option value="">全部方向</option><option value="long">上行假设</option><option value="short">回落假设</option><option value="neutral">区间假设</option></select></label>
      </div>
      <Stats stats={aiStats} />
      <p className="mt-3 text-xs leading-5 text-t-text3">统计范围：{filterSymbol || '全部标的'}、全部方向、最近 90 天。下方为全部历史明细，方向筛选不改变统计。</p>
      {statsFailure ? <p className="mt-2 text-xs leading-5 text-t-down">统计暂时无法读取。{scopedStats ? '保留上次成功读取的统计。' : '明细仍可独立查看。'}</p> : null}
      {loading && !page ? <p role="status" className="flex items-center gap-2 py-8 text-sm text-t-text2"><RefreshCw size={16} className="animate-spin" />正在读取判断记录…</p> : null}
      {page && !page.items.length ? <div className="py-8 text-sm leading-6 text-t-text2"><Target size={24} className="mb-3 text-t-text3" />当前范围暂无判断记录。<p className="mt-2 text-xs leading-5 text-t-text3">在个股看板生成 AI 判断后，原结论与后续结果会保留在这里。</p></div> : null}
      {page ? <>
        <div className="mt-4 divide-y divide-t-divider">{page.items.map((item) => {
          const status = item.outcome?.status || item.prediction.status;
          const directionText = getPredictionDirectionPresentation(item.prediction.direction, status);
          return <button key={item.prediction.prediction_id} type="button" onClick={() => selectRecord(item.prediction.prediction_id)} data-testid="personal-record-row" className="block w-full py-4 text-left hover:bg-t-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-t-accent">
            <div className="flex flex-wrap items-center justify-between gap-2"><span className="text-sm font-semibold text-t-text">{item.prediction.symbol}</span><span className="text-xs text-t-text2">{isTerminalPredictionStatus(status) ? '历史 · ' : ''}{PERSONAL_OUTCOME_LABELS[status] || status}</span></div>
            <p className="mt-2 text-sm text-t-text">{item.prediction.source_type === 'manual' ? directionText.label.replace(/^AI /, '手动 ') : directionText.label}</p>
            <p className="mt-2 line-clamp-2 break-words text-sm leading-6 text-t-text2">{item.prediction.thesis}</p>
            <p className="mt-2 text-xs text-t-text3">{formatPersonalTime(item.prediction.created_at)}</p>
          </button>;
        })}</div>
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-t-divider pt-4">
          <p className="text-xs text-t-text3" aria-live="polite">{page.items.length ? `第 ${page.offset + 1}–${page.offset + page.items.length} 条` : '暂无记录'}</p>
          <nav className="flex gap-2" aria-label="我的判断分页">
            <button type="button" title="上一页" aria-label="上一页我的判断" className={controlClass} disabled={loading || page.offset === 0} onClick={() => { setOffset(Math.max(0, page.offset - PERSONAL_PAGE_SIZE)); refresh(); }}><ChevronLeft size={16} /></button>
            <button type="button" title="下一页" aria-label="下一页我的判断" className={controlClass} disabled={loading || !page.hasMore} onClick={() => { setOffset(page.offset + PERSONAL_PAGE_SIZE); refresh(); }}><ChevronRight size={16} /></button>
          </nav>
        </div>
      </> : null}
    </>}
  </div>;
}

export function RightPanelTrackRecordTab({ symbol, initialView }: { symbol?: string; initialView?: TrackRecordView }) {
  const location = useLocation();
  const userId = useStore((state) => state.authIdentity?.userId);
  const normalizedSymbol = symbol?.trim().toUpperCase() || undefined;
  const [view, setView] = useState<TrackRecordView>(initialView || (userId ? 'personal' : 'us20'));
  const viewSelectedRef = useRef(false);
  useEffect(() => {
    if (!initialView && !viewSelectedRef.current) setView(userId ? 'personal' : 'us20');
  }, [userId, initialView]);
  return <div className="min-w-0 px-4 py-5 sm:px-5" data-testid="right-panel-track-record">
    <div className="mb-5 grid grid-cols-2 gap-1 rounded-md bg-t-bg p-1" role="tablist" aria-label="战绩账本">
      {([['personal', '我的判断'], ['us20', 'US20 基准']] as const).map(([value, label]) => <button type="button" key={value} role="tab" aria-selected={view === value} onClick={() => { viewSelectedRef.current = true; setView(value); }} className={`min-h-10 rounded px-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-t-accent ${view === value ? 'bg-t-hover font-medium text-t-text' : 'text-t-text2 hover:text-t-text'}`}>{label}</button>)}
    </div>
    {view === 'us20' ? <BenchmarkTrackRecordView shareLink /> : userId ? <PersonalTrackRecordView key={userId} symbol={normalizedSymbol} /> : <div className="py-7 text-sm text-t-text2" data-testid="personal-track-record-login">
      <LogIn size={24} className="mb-3 text-t-text3" />
      <p className="leading-6">登录后查看自己的 AI 判断与复盘结果。</p>
      <Link to={`/welcome?from=${encodeURIComponent(`${location.pathname}${location.search}`)}`} className="mt-4 inline-flex min-h-10 items-center gap-2 rounded-md bg-t-accent px-3 text-sm text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-t-accent"><LogIn size={16} />登录</Link>
    </div>}
  </div>;
}
