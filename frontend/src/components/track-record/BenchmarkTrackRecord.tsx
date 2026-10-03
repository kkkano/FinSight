import { useEffect, useRef, useState } from 'react';
import { ArrowLeft, ChevronLeft, ChevronRight, Clock3, ExternalLink, Info, RefreshCw } from 'lucide-react';
import { apiClient } from '../../api/client';
import type { TrackRecordFilters } from '../../api/domains/trackRecord';
import type { PredictionGroup, PredictionRecord, PredictionTrackRecord, PredictionType } from '../../types/predictions';
import {
  EARLY_SAMPLE_SIZE, agentLabel, directionLabel, formatDelta, formatEtTime,
  formatHitRate, formatRatio, predictionLabel, sortGroups, sortRecentRecords, statusLabel,
} from '../../pages/trackRecord';

const controlClass = 'min-h-10 rounded-md border border-t-border bg-t-surface px-3 text-sm text-t-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-t-accent disabled:opacity-40';
const sectionClass = 'border-t border-t-divider py-5';
const recordStatuses = ['pending', 'settled', 'awaiting_data', 'failed', 'missed', 'abstained', 'queued', 'running', 'interrupted', 'invalid'];

function Metric({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return <div className="min-w-0">
    <dt className="text-xs leading-5 text-t-text3">{label}</dt>
    <dd className="mt-1 text-xl font-semibold tabular-nums text-t-text">{value}</dd>
    {detail ? <dd className="mt-1 text-xs leading-5 text-t-text2">{detail}</dd> : null}
  </div>;
}

function GroupResult({ group }: { group: PredictionGroup }) {
  return <article className="min-w-0 rounded-lg border border-t-border px-4 py-4" data-testid="prediction-model-group" data-confirmed={group.model_confirmed}>
    <h4 className="break-words text-sm font-semibold text-t-text">{group.actual_model || '未知模型'}</h4>
    <p className={`mt-1 text-xs ${group.model_confirmed ? 'text-t-text3' : 'text-t-warning'}`}>{group.model_confirmed ? '供应商已确认模型' : '模型身份未确认'}</p>
    {group.n > 0 ? <>
      <dl className="mt-4 grid grid-cols-2 gap-4">
        <Metric label="AI 命中率" value={formatHitRate(group.hit_rate, group.n)} detail={`${group.hits} / ${group.n} 命中`} />
        <Metric label="同样本基准" value={formatHitRate(group.baseline_hit_rate, group.n)} detail={`${group.baseline_hits} / ${group.n} 命中`} />
      </dl>
      <div className="mt-4 space-y-1 border-t border-t-divider pt-3 text-sm">
        <p className={group.delta !== null && group.delta < 0 ? 'text-t-down' : 'text-t-text'} data-testid="prediction-baseline-delta">AI − 基准：{formatDelta(group.delta, group.n)}</p>
        <p className="text-xs text-t-text3">已结算 n = {group.n}{group.n < EARLY_SAMPLE_SIZE ? ' · 样本不足' : ''}</p>
      </div>
      {group.prediction_type === 'drawdown' ? <details className="mt-3 text-sm">
        <summary className="cursor-pointer text-t-text2">预警与漏报明细</summary>
        <p className="mt-3 text-xs leading-5 text-t-text3">实际事件发生率：{formatRatio((group.tp + group.fn) / group.n)}（{group.tp + group.fn} / {group.n}）</p>
        <dl className="mt-3 grid grid-cols-2 gap-3 text-xs" aria-label="风险混淆计数">
          {[
            ['TP · 正确预警', group.tp], ['FP · 误报', group.fp],
            ['TN · 正确排除', group.tn], ['FN · 漏报', group.fn],
          ].map(([label, count]) => <div key={label}><dt className="text-t-text3">{label}</dt><dd className="mt-1 text-base font-medium tabular-nums text-t-text">{count}</dd></div>)}
        </dl>
      </details> : null}
    </> : <p className="mt-4 text-sm text-t-text2">等待首批结算</p>}
    <details className="mt-4 border-t border-t-divider pt-3 text-xs">
      <summary className="cursor-pointer text-t-text2">版本与评分来源</summary>
      <dl className="mt-3 space-y-2 break-words leading-5 text-t-text3">
        <div><dt>Agent</dt><dd className="text-t-text2">{agentLabel(group.agent)}</dd></div>
        <div><dt>提示版本</dt><dd className="text-t-text2">{group.prompt_version || '--'}</dd></div>
        <div><dt>策略版本</dt><dd className="text-t-text2">{group.strategy_version || '--'}</dd></div>
        <div><dt>评分版本</dt><dd className="text-t-text2">{group.scorer_version || '--'}</dd></div>
      </dl>
    </details>
  </article>;
}

function TaskResults({ type, data }: { type: PredictionType; data: PredictionTrackRecord }) {
  const groups = sortGroups(data.groups.filter((group) => group.prediction_type === type));
  const confirmed = groups.filter((group) => group.model_confirmed);
  const unconfirmed = groups.filter((group) => !group.model_confirmed);
  const isRisk = type === 'drawdown';
  return <section className={sectionClass} aria-labelledby={`${type}-results-title`} data-testid={`${type}-results`}>
    <h2 id={`${type}-results-title`} className="text-base font-semibold text-t-text">{isRisk ? '5 日回撤事件 · Risk' : '5 日方向 · Technical'}</h2>
    <p className="mt-2 text-xs leading-5 text-t-text2">{isRisk
      ? `最大回撤 ≥ ${formatRatio(data.metadata.drawdown_threshold)} 为发生。基准：始终不发生。`
      : `上涨 > +${formatRatio(data.metadata.direction_threshold)}，下跌 < −${formatRatio(data.metadata.direction_threshold)}，其余为横盘。基准：永远看多。`}</p>
    {!groups.length ? <p className="mt-4 flex items-center gap-2 text-sm text-t-text2"><Clock3 size={16} />等待首批结算</p> : null}
    <div className="mt-4 grid gap-3">{confirmed.map((group) => <GroupResult key={[group.actual_model, group.prompt_version, group.strategy_version, group.scorer_version].join('|')} group={group} />)}</div>
    {unconfirmed.length ? <div className="mt-5 space-y-3" data-testid={`${type}-unconfirmed-models`}>
      <h3 className="text-sm font-medium text-t-text">模型身份未确认 · 单独统计</h3>
      <p className="text-xs leading-5 text-t-text3">供应商未确认实际模型名称，以下记录不并入已确认模型。</p>
      {unconfirmed.map((group) => <GroupResult key={[group.actual_model, group.prompt_version, group.strategy_version, group.scorer_version].join('|')} group={group} />)}
    </div> : null}
  </section>;
}

function RecordOutcome({ record }: { record: PredictionRecord }) {
  const outcome = record.outcome;
  if (!outcome || record.status !== 'settled') return <>
    <p className="text-sm text-t-text2">{statusLabel(record.status)}</p>
    <p className="mt-2 text-sm leading-6 text-t-text3">{record.status === 'awaiting_data' || record.status === 'invalid'
      ? '保留原窗口，等待同源行情核验。'
      : record.status === 'pending' ? '尚未产生已核验结果，不计为命中或未命中。' : '此次机会未形成可评分结果，仍保留在覆盖记录中。'}</p>
  </>;
  return <div className="space-y-3 text-sm">
    <p className={`font-medium ${outcome.hit ? 'text-t-up' : 'text-t-down'}`}>已结算 · {outcome.hit ? '命中' : '未命中'}</p>
    <p className="text-t-text">{record.prediction_type === 'direction'
      ? `实际${directionLabel(outcome.actual_direction)} · 收益 ${formatRatio(outcome.return_pct)}`
      : `实际${outcome.actual_event ? '发生' : '未发生'} · 最大回撤 ${formatRatio(outcome.max_drawdown)}`}</p>
    <p className="text-t-text2">同样本基准：{outcome.baseline_hit ? '命中' : '未命中'}</p>
    <dl className="grid grid-cols-2 gap-4">
      <Metric label="P0 · 首个时段开盘" value={outcome.p0.toFixed(2)} />
      <Metric label="P5 · 第 5 日收盘" value={outcome.p5.toFixed(2)} />
    </dl>
  </div>;
}

export function BenchmarkRecordDetail({ record, source }: { record: PredictionRecord; source: string }) {
  return <article className="min-w-0" data-testid="benchmark-record-detail">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h3 className="text-lg font-semibold text-t-text">{record.ticker}</h3>
      <span className="text-xs text-t-text2">{statusLabel(record.status)}</span>
    </div>
    <p className="mt-1 text-xs leading-5 text-t-text3">{agentLabel(record.agent)} · {record.prediction_type === 'direction' ? '5 日方向' : '5 日回撤事件'} · 批次 {record.batch_date}</p>
    <section className={sectionClass}>
      <h4 className="text-sm font-semibold text-t-text">预先判断</h4>
      <p className="mt-2 text-base font-medium text-t-text">{predictionLabel(record)}</p>
      <p className="mt-3 break-words text-sm leading-6 text-t-text2">{record.reason || '未形成有效预测依据'}</p>
      {record.error_code ? <p className="mt-3 break-all text-xs leading-5 text-t-down">失败 / 数据原因：{record.error_code}</p> : null}
    </section>
    <section className={sectionClass}>
      <h4 className="mb-3 text-sm font-semibold text-t-text">实际结果</h4>
      <RecordOutcome record={record} />
    </section>
    <section className={sectionClass}>
      <h4 className="text-sm font-semibold text-t-text">生成、行情与模型来源</h4>
      <dl className="mt-3 space-y-3 break-words text-sm">
        {[
          ['预测发布', record.issued_at ? formatEtTime(record.issued_at) : '--'],
          ['评估窗口', `${formatEtTime(record.window_start)} → ${formatEtTime(record.window_end)}`],
          ['结算时间', record.outcome ? formatEtTime(record.outcome.settled_at) : '--'],
          ['行情来源', record.outcome?.source || source],
          ['实际模型', record.actual_model || '--'],
          ['模型身份', record.model_confirmed ? '供应商已确认' : '未确认，单独统计'],
          ['提示版本', record.prompt_version || '--'],
        ].map(([label, value]) => <div key={label}><dt className="text-xs text-t-text3">{label}</dt><dd className="mt-1 text-t-text2">{value}</dd></div>)}
      </dl>
      <details className="mt-4 text-sm">
        <summary className="cursor-pointer text-t-text2">输入证据</summary>
        <p className="mt-2 break-all text-xs leading-5 text-t-text3">{record.evidence_refs.length ? record.evidence_refs.join('、') : '无有效输入证据'}</p>
      </details>
    </section>
  </article>;
}

export function TrackRecordContent({ data, loading = false, pageError = false, onPageChange }: {
  data: PredictionTrackRecord; loading?: boolean; pageError?: boolean; onPageChange?: (offset: number) => void;
}) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const recordListRef = useRef<HTMLElement>(null);
  const selectRecord = (id: string | null) => {
    setSelectedId(id);
    contentRef.current?.scrollIntoView({ block: 'start' });
  };
  const records = sortRecentRecords(data.records);
  const selected = records.find((record) => record.id === selectedId);
  const { summary, coverage, metadata, universe, pagination } = data;
  const offset = pagination?.offset ?? 0;
  const limit = pagination?.limit ?? 50;
  const total = pagination?.total ?? summary.opportunities;
  const coverageRatio = coverage.expected > 0 ? Math.min(1, coverage.accepted / coverage.expected) : 0;
  if (selected) return <div ref={contentRef}>
    <button type="button" onClick={() => selectRecord(null)} className="mb-4 inline-flex min-h-10 items-center gap-2 text-sm text-t-text2 hover:text-t-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-t-accent"><ArrowLeft size={16} />返回战绩</button>
    <BenchmarkRecordDetail record={selected} source={metadata.source} />
  </div>;
  return <div ref={contentRef} data-testid="benchmark-track-record-content">
    <button type="button" onClick={() => recordListRef.current?.scrollIntoView({ block: 'start' })} className="mb-4 inline-flex min-h-10 items-center gap-2 rounded-md bg-t-hover px-3 text-sm text-t-text2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-t-accent">机会与预测明细 <ChevronRight size={16} /></button>
    <p className={`text-sm font-medium ${data.enabled ? 'text-t-accent' : 'text-t-text2'}`}>{data.enabled ? '固定采集已启用' : '固定采集尚未启用'}</p>
    <p className="mt-1 text-xs leading-5 text-t-text3">{universe.tickers.length} 只美股 · 每日 {universe.tickers.length * 2} 个机会 · {metadata.horizon_sessions} 个交易日</p>
    {!data.enabled ? <p className="mt-3 text-sm leading-6 text-t-text2">采集关闭期间不会产生新预测。已有记录继续保留；战绩只在取得真实结果后展示。</p> : null}
    <dl className="grid grid-cols-2 gap-x-5 gap-y-5 py-5" aria-label="累计样本概览">
      <Metric label="已结算 · 成熟样本" value={String(summary.settled)} detail="仅已结算记录进入命中率分母" />
      <Metric label="待结算" value={String(summary.pending)} detail={`另有 ${summary.awaiting_data} 条等待行情`} />
      <Metric label="已接受 / 全部机会" value={`${summary.predictions} / ${summary.opportunities}`} />
      <Metric label="累计批次 / 股票" value={`${summary.batch_count} / ${summary.stock_count}`} />
    </dl>
    <section className={sectionClass} data-testid="prediction-coverage">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><h2 className="text-sm font-semibold text-t-text">最近批次覆盖</h2><p className="mt-1 text-xs leading-5 text-t-text3">{coverage.batch_date ? `${coverage.batch_date} · 美东交易日` : '尚无采集批次'}</p></div>
        <p className="text-lg font-semibold tabular-nums text-t-text">{coverage.accepted} / {coverage.expected}</p>
      </div>
      <div className="mt-3 h-1.5 overflow-hidden rounded bg-t-hover" role="progressbar" aria-label="最近批次预测覆盖" aria-valuemin={0} aria-valuemax={coverage.expected || 40} aria-valuenow={coverage.accepted}><div className="h-full bg-t-accent" style={{ width: `${coverageRatio * 100}%` }} /></div>
      <p className="mt-3 text-xs leading-5 text-t-text2">已尝试 {coverage.attempts} 次 · 最近进展 {formatEtTime(coverage.last_update)}</p>
      <p className="mt-2 text-xs leading-5 text-t-text3">累计：预测失败 {summary.failed} · 错过登记 {summary.missed} · 主动弃权 {summary.abstained}</p>
      {Object.keys(coverage.counts).length ? <p className="mt-2 text-xs leading-5 text-t-text3">最近批次：{Object.entries(coverage.counts).map(([status, count]) => `${statusLabel(status)} ${count}`).join(' · ')}</p> : null}
    </section>
    <div className="flex items-start gap-2 border-t border-t-divider py-4 text-xs leading-5 text-t-text2" role="note">
      <Info size={16} className="mt-0.5 shrink-0 text-t-text3" />
      <div>
        {!summary.settled ? <p className="mb-2 text-sm font-medium text-t-text">等待首批结算。需自然经过 5 个交易日并取得完整行情。</p> : null}
        <p>每组少于 {EARLY_SAMPLE_SIZE} 条成熟记录标记“样本不足”，并非显著性检验。滚动 5 日窗口存在重叠，记录并非独立样本。</p>
        <p className="mt-2">以下汇总为全部公开历史，明细筛选与翻页不改变统计。未命中、失败及低于基准的结果同样保留，不代表投资收益。</p>
      </div>
    </div>
    <TaskResults type="direction" data={data} />
    <TaskResults type="drawdown" data={data} />
    <section ref={recordListRef} className={sectionClass} aria-labelledby="prediction-records-title" aria-busy={loading}>
      <h2 id="prediction-records-title" className="text-base font-semibold text-t-text">机会与预测明细</h2>
      <p className="mt-2 text-xs leading-5 text-t-text3">原判断、实际结果与生成来源 · 按批次日期倒序</p>
      {pageError ? <p role="status" className="mt-3 text-sm leading-6 text-t-down">读取失败，仍显示上次成功加载的记录。请刷新重试。</p> : null}
      {!records.length ? <p className="py-6 text-sm leading-6 text-t-text2">{summary.opportunities ? '当前筛选下暂无记录。' : '尚无前瞻预测记录。真实战绩将从首次采集开始累积。'}</p> : <div className="mt-3 divide-y divide-t-divider">
        {records.map((record) => <button type="button" key={record.id} onClick={() => selectRecord(record.id)} className="block w-full px-1 py-4 text-left hover:bg-t-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-t-accent" data-testid="prediction-record-row">
          <div className="flex flex-wrap items-center justify-between gap-2"><span className="text-sm font-semibold text-t-text">{record.ticker} · {record.prediction_type === 'direction' ? '5 日方向' : '5 日回撤'}</span><span className="text-xs text-t-text2">{record.status === 'settled' && record.outcome ? record.outcome.hit ? '已结算 · 命中' : '已结算 · 未命中' : statusLabel(record.status)}</span></div>
          <p className="mt-2 text-sm text-t-text">{predictionLabel(record)}</p>
          <p className="mt-1 break-words text-xs leading-5 text-t-text3">{record.batch_date} · {record.actual_model || '未知模型'}</p>
        </button>)}
      </div>}
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <p className="text-xs text-t-text3" data-testid="prediction-page-range" aria-live="polite">{records.length ? `第 ${offset + 1}–${offset + records.length} 条，共 ${total} 条` : `共 ${total} 条记录`}</p>
        <nav className="flex gap-2" aria-label="预测明细分页">
          <button type="button" title="上一页" aria-label="上一页预测明细" className={controlClass} disabled={loading || offset === 0 || !onPageChange} onClick={() => onPageChange?.(Math.max(0, offset - limit))}><ChevronLeft size={16} /></button>
          <button type="button" title="下一页" aria-label="下一页预测明细" className={controlClass} disabled={loading || !pagination?.has_more || !onPageChange} onClick={() => onPageChange?.(offset + limit)}><ChevronRight size={16} /></button>
        </nav>
      </div>
    </section>
    <details className={sectionClass}>
      <summary className="cursor-pointer text-sm font-medium text-t-text">评分口径与固定样本池</summary>
      <div className="mt-3 space-y-3 text-xs leading-5 text-t-text2">
        <p>P0 为预定首个常规交易时段开盘价；P5 为包含起始日在内第 5 个交易日的收盘价。方向收益 = P5 / P0 − 1；阈值相等归为横盘。</p>
        <p>回撤使用 P0 与随后 5 个收盘价构成的序列，计算相对此前运行高点的最大降幅；不用日内最低价或期末跌幅代替。现金分红不计入收益。</p>
        <p>方向与回撤分别用完全相同的已结算记录对照基准，不合并排名。提示、策略或实际模型变化后分组展示，旧版本保留。</p>
        <p>每日美东 08:45 开始、09:20 截止登记；每只股票 2 个机会。失败、弃权与错过登记均保留，不能事后补写。</p>
        <p className="break-words">固定样本池 · {universe.version}：{universe.tickers.join('、')}</p>
        <p className="break-words">行情来源：{metadata.source}</p>
      </div>
    </details>
  </div>;
}

export function BenchmarkTrackRecordView({ shareLink = false }: { shareLink?: boolean }) {
  const [filters, setFilters] = useState<TrackRecordFilters>({});
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [result, setResult] = useState<{ key: string; data: PredictionTrackRecord } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const { ticker, status, prediction_type: type } = filters;
  const queryKey = JSON.stringify([ticker, status, type]);
  const data = result?.key === queryKey ? result.data : null;
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(false);
    apiClient.getPredictionTrackRecord(20, offset, controller.signal, { ticker, status, prediction_type: type }).then((response) => {
      if (!controller.signal.aborted) setResult({ key: queryKey, data: response });
    }).catch(() => {
      if (!controller.signal.aborted) setError(true);
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [ticker, status, type, offset, queryKey, refresh]);
  const changeFilters = (next: TrackRecordFilters) => { setFilters(next); setOffset(0); };
  return <div className="min-w-0" data-testid="us20-track-record">
    <div className="flex flex-wrap items-start justify-between gap-3 pb-4">
      <div><h2 className="text-base font-semibold text-t-text">US20 固定样本基准</h2><p className="mt-1 text-xs leading-5 text-t-text3">独立公开账本，不与我的判断混算。</p></div>
      <div className="flex gap-2">
        {shareLink ? <a href="/track-record" target="_blank" rel="noopener noreferrer" title="打开公开分享页" aria-label="打开公开分享页" className={`${controlClass} inline-flex items-center`}><ExternalLink size={16} /></a> : null}
        <button type="button" title="刷新战绩" aria-label="刷新战绩" className={controlClass} disabled={loading} onClick={() => setRefresh((value) => value + 1)}><RefreshCw size={16} className={loading ? 'animate-spin' : ''} /></button>
      </div>
    </div>
    <div className="grid grid-cols-2 gap-3 border-b border-t-divider pb-5">
      <label className="min-w-0 text-xs text-t-text3">标的<select aria-label="US20 标的筛选" className={`${controlClass} mt-1 w-full`} value={ticker || ''} onChange={(event) => changeFilters({ ...filters, ticker: event.target.value || undefined })}><option value="">全部 20 只</option>{result?.data.universe.tickers.map((symbol) => <option key={symbol} value={symbol}>{symbol}</option>)}</select></label>
      <label className="min-w-0 text-xs text-t-text3">状态<select aria-label="US20 状态筛选" className={`${controlClass} mt-1 w-full`} value={status || ''} onChange={(event) => changeFilters({ ...filters, status: event.target.value || undefined })}><option value="">全部状态</option>{recordStatuses.map((value) => <option key={value} value={value}>{statusLabel(value)}</option>)}</select></label>
      <label className="col-span-2 min-w-0 text-xs text-t-text3">任务<select aria-label="US20 任务筛选" className={`${controlClass} mt-1 w-full`} value={type || ''} onChange={(event) => changeFilters({ ...filters, prediction_type: event.target.value as PredictionType || undefined })}><option value="">方向与回撤</option><option value="direction">5 日方向</option><option value="drawdown">5 日回撤事件</option></select></label>
      <p className="col-span-2 text-xs leading-5 text-t-text3">筛选仅作用于明细；模型战绩与覆盖率包含全部历史。</p>
    </div>
    {error ? <p role="alert" className="py-4 text-sm leading-6 text-t-down">战绩数据暂时无法读取，请刷新重试。{data ? '保留上次成功加载的数据。' : ''}</p> : null}
    {loading && !data ? <p role="status" className="flex items-center gap-2 py-8 text-sm text-t-text2"><RefreshCw size={16} className="animate-spin" />正在读取公开预测账本…</p> : null}
    {data ? <div className="pt-5"><TrackRecordContent data={data} loading={loading} pageError={error} onPageChange={(nextOffset) => { setOffset(nextOffset); setRefresh((value) => value + 1); }} /></div> : null}
  </div>;
}
