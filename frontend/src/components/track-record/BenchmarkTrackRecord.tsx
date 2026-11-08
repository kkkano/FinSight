import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { ChevronDown, ChevronLeft, ChevronRight, RefreshCw } from 'lucide-react';
import { apiClient } from '../../api/client';
import type { TrackRecordFilters } from '../../api/domains/trackRecord';
import type { PredictionGroup, PredictionRecord, PredictionTrackRecord } from '../../types/predictions';
import { directionLabel, formatEtTime, formatRatio, predictionLabel, sortGroups, sortRecentRecords, statusLabel } from '../../pages/trackRecord';
import { sourceDisplayName } from '../../utils/sourceDisplayName';
import EChart from '../charts/EChart';
import { useStore } from '../../store/useStore';
import { useSearchParams } from 'react-router-dom';
import { chartTokens } from '../dashboard/visualTokens';

const groupKey = (group: PredictionGroup) => [group.actual_model, group.prompt_version, group.strategy_version, group.scorer_version].join('|');
const recordStatuses = ['pending', 'settled', 'awaiting_data', 'failed', 'missed', 'abstained', 'queued', 'running', 'interrupted', 'invalid'];
const dateOnly = (value?: string | null) => value ? value.slice(0, 10) : '暂无';
function pendingText(value: string): string {
  const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
  return value.slice(0, 10) < today ? `等待 ${formatEtTime(value)} 的行情完成对账` : `${formatEtTime(value)} 收盘后自动对账`;
}
function outcomeLabel(record: PredictionRecord): string {
  if (record.status === 'settled' && record.outcome) {
    if (record.prediction_type === 'direction') return record.outcome.hit ? '猜中' : '没猜中';
    return record.event_occurs ? record.outcome.actual_event ? '预警成功' : '虚惊一场' : record.outcome.actual_event ? '漏报' : '正常排除';
  }
  if (['pending', 'awaiting_data', 'queued', 'running'].includes(record.status)) return '等待对账';
  return '无法评分（不计入）';
}
function confidence(record: PredictionRecord): string {
  const value = record.confidence;
  if (typeof value === 'number' && Number.isFinite(value)) return `${(value <= 1 ? value * 100 : value).toFixed(0)}%`;
  if (typeof value === 'string') return ({ high: '高', medium: '中', low: '低' } as Record<string, string>)[value] || value;
  return '未提供';
}
function deltaText(group?: PredictionGroup): string {
  if (!group || !group.n || group.delta == null) return '尚无可比较的对账结果';
  const amount = Math.abs(group.delta * 100).toFixed(1);
  return group.delta === 0 ? '和每次都猜涨相比：持平' : `和每次都猜涨比：${group.delta > 0 ? '高' : '低'} ${amount} 个百分点`;
}
function versionLabel(value?: string | null): string { return (value || '未提供').replace(/us20/gi, '固定样本').replace(/technical/gi, '方向').replace(/risk/gi, '回撤').replace(/\bP0\b/g, '起点').replace(/\bP5\b/g, '终点'); }
function modelName(group: PredictionGroup): string { return versionLabel(group.actual_model); }

export function BenchmarkRecordDetail({ record, source }: { record: PredictionRecord; source: string }) {
  return <article data-testid="benchmark-record-detail" className="grid gap-4 py-4 text-sm md:grid-cols-2">
    <section><h3 className="font-semibold text-t-text">当时的判断</h3><p className="mt-2 text-t-text2">{predictionLabel(record)} · {confidence(record)}</p><p className="mt-2 whitespace-pre-wrap leading-7 text-t-text2">{record.reason || '当时未留下可用的判断依据。'}</p><p className="design-caption mt-2">发布于 {formatEtTime(record.issued_at)}</p></section>
    <section><h3 className="font-semibold text-t-text">实际对账行情</h3>{record.outcome && record.status === 'settled' ? <dl className="mt-2 grid grid-cols-2 gap-3">
      <div><dt className="design-caption">起点价</dt><dd className="num">{record.outcome.p0.toFixed(2)}</dd></div><div><dt className="design-caption">终点价</dt><dd className="num">{record.outcome.p5.toFixed(2)}</dd></div>
      <div><dt className="design-caption">实际涨跌</dt><dd className="num">{formatRatio(record.outcome.return_pct)}</dd></div><div><dt className="design-caption">期间最大回撤</dt><dd className="num">{formatRatio(record.outcome.max_drawdown)}</dd></div>
    </dl> : <p className="mt-2 leading-6 text-t-text3">{record.status === 'pending' ? pendingText(record.window_end) : statusLabel(record.status)}</p>}
      <p className="design-caption mt-3">{sourceDisplayName(record.outcome?.source || source)} · {record.outcome ? formatEtTime(record.outcome.settled_at) : '尚未完成对账'}</p><p className="design-caption mt-2">使用的模型：{versionLabel(record.actual_model)} · {record.model_confirmed ? '实际模型已确认' : '实际模型尚未确认，单独统计'}</p>
      {record.error_code && <p className="mt-2 text-xs text-t-text3">这条记录未取得可评分结果，保留原判断供核对。</p>}
      {record.settlement_bars?.length ? <details className="mt-3"><summary className="cursor-pointer text-xs text-t-accent">查看逐日对账行情</summary><div className="mt-2 overflow-x-auto"><table className="design-table"><thead><tr><th>日期</th><th>开盘</th><th>收盘</th></tr></thead><tbody>{record.settlement_bars.slice(0,10).map((bar,index)=><tr key={index}><td className="num">{String(bar.date||bar.time||bar.Date||'暂无')}</td><td className="num">{String(bar.open??bar.Open??'暂无')}</td><td className="num">{String(bar.close??bar.Close??'暂无')}</td></tr>)}</tbody></table></div></details> : null}
    </section>
  </article>;
}

function CumulativeChart({ data, group }: { data: PredictionTrackRecord; group?: PredictionGroup }) {
  const dark = useStore((state) => state.theme === 'dark');
  const directionGroups = data.groups.filter((item) => item.prediction_type === 'direction' && item.model_confirmed);
  const rows = (data.daily_series || []).filter((row) => row.n > 0 && row.hit_rate != null && row.baseline_hit_rate != null)
    .filter((row) => !row.actual_model ? directionGroups.length <= 1 : group && row.actual_model === group.actual_model && row.prompt_version === group.prompt_version && row.strategy_version === group.strategy_version && row.scorer_version === group.scorer_version);
  const colors=chartTokens();
  const option = useMemo(() => ({ animation: false, color: [colors.accent, colors.text], grid: { left: 42, right: 115, top: 10, bottom: 30 }, tooltip: { trigger: 'axis', valueFormatter: (value: number) => `${value.toFixed(1)}%` },
    legend: { show: false, top: 0, textStyle: { color: colors.text, fontSize: 11 } },
    xAxis: { type: 'category', data: rows.map((row) => row.date), boundaryGap: false, axisLabel: { color: colors.text, fontFamily: 'JetBrains Mono Variable', fontSize: 10 }, axisLine: { lineStyle: { color: colors.border } }, axisTick: { show: false } },
    yAxis: { type: 'value', min: 0, max: 100, axisLabel: { formatter: '{value}%', color: colors.text, fontSize: 10 }, splitLine: { lineStyle: { color: colors.line } } },
    series: [{ name: '预测命中率', type: 'line', data: rows.map((row) => row.hit_rate! * 100), symbol: 'none', endLabel: { show: true, formatter: (params: { value: number }) => `FinSight ${params.value.toFixed(1)}%`, color: colors.accent, fontSize: 12, fontFamily: 'JetBrains Mono Variable' }, labelLayout: { moveOverlap: 'shiftY' }, lineStyle: { width: 2.2, color: colors.accent } }, { name: '每次都猜涨', type: 'line', data: rows.map((row) => row.baseline_hit_rate! * 100), symbol: 'none', endLabel: { show: true, formatter: (params: { value: number }) => `每次猜涨 ${params.value.toFixed(1)}%`, color: colors.text, fontSize: 11, fontFamily: 'JetBrains Mono Variable' }, labelLayout: { moveOverlap: 'shiftY' }, lineStyle: { width: 1.6, type: 'dashed', color: colors.text } }] }), [rows, dark]);
  return <section className="design-card"><div className="mb-2 flex flex-wrap items-baseline gap-2"><h2 className="text-sm font-semibold">累计方向命中率</h2><span className="design-caption">按真实对账日累计，与每次都猜涨比较</span></div>
    {rows.length ? <EChart option={option} style={{ height: 226 }} /> : <div className="design-empty">暂时没有累计曲线，数据齐全后会显示。</div>}
  </section>;
}

export function TrackRecordContent({ data, loading = false, pageError = false, onPageChange, filterControls }: {
  data: PredictionTrackRecord; loading?: boolean; pageError?: boolean; onPageChange?: (offset: number) => void; filterControls?: ReactNode;
}) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const [directionKey, setDirectionKey] = useState('');
  const [riskKey, setRiskKey] = useState('');
  const directions = sortGroups(data.groups.filter((item) => item.prediction_type === 'direction' && item.model_confirmed));
  const risks = sortGroups(data.groups.filter((item) => item.prediction_type === 'drawdown' && item.model_confirmed));
  const direction = directions.find((item) => groupKey(item) === directionKey) || directions[0];
  const risk = risks.find((item) => groupKey(item) === riskKey) || risks[0];
  const unconfirmed = data.groups.filter((item) => !item.model_confirmed);
  const { metadata, summary, coverage, pagination } = data;
  const horizon = metadata.horizon_sessions;
  const records = sortRecentRecords(data.records);
  const waiting = metadata.next_settlement_date || records.filter((record) => record.status === 'pending').map((record) => record.window_end).sort()[0];
  const total = pagination?.total ?? summary.opportunities;
  const offset = pagination?.offset ?? 0;
  const groupPicker = (groups: PredictionGroup[], value: PredictionGroup | undefined, change: (value: string) => void) => groups.length > 1 ? <label className="design-caption mt-2 block">分别查看模型版本<select className="mt-1 w-full rounded-md border border-t-border bg-t-surface p-1 text-xs" value={value ? groupKey(value) : ''} onChange={(event) => change(event.target.value)}>{groups.map((item) => <option key={groupKey(item)} value={groupKey(item)}>{modelName(item)} · {versionLabel(item.strategy_version)} · {versionLabel(item.scorer_version)}</option>)}</select></label> : value ? <p className="design-caption mt-2">使用的模型：{modelName(value)}</p> : null;
  return <div className="flex flex-col gap-5" data-testid="benchmark-track-record-content">
    {!data.enabled && <p className="design-caption" role="status">自动预测尚未开启，已有记录仍可查看。</p>}
    <div className="track-record-metrics">
      <section className="design-card" data-testid="direction-results"><div className="design-caption">方向命中率</div><div className="track-record-number num">{direction?.n ? formatRatio(direction.hit_rate) : '暂无'}</div><p className="text-[13px] text-t-text2">{direction?.n ? `${direction.n} 次已对账中猜中 ${direction.hits} 次` : '等待首批对账'}</p>{direction&&metadata.min_sample_size!=null&&direction.n>0&&direction.n<metadata.min_sample_size&&<p className="design-caption">记录还太少，结论不可靠</p>}<p className="design-caption mt-1.5">基准：每次都猜涨，猜中 {direction?.n ? formatRatio(direction.baseline_hit_rate) : '暂无'}</p><p className={`mt-1 text-xs ${direction?.delta != null && direction.delta > 0 ? 'text-t-accent' : 'text-t-text3'}`} data-testid="prediction-baseline-delta">{deltaText(direction)}</p>{groupPicker(directions,direction,setDirectionKey)}</section>
      <section className="design-card" data-testid="drawdown-results"><div className="design-caption">大跌预警</div><div className="track-record-number num">{risk?.n && risk.tp + risk.fn > 0 ? `${risk.tp} / ${risk.tp + risk.fn}` : '暂无'}</div><p className="text-[13px] text-t-text2">{risk?.n ? risk.tp + risk.fn > 0 ? `${risk.tp + risk.fn} 次真实大跌里，提前预警了 ${risk.tp} 次` : `已对账 ${risk.n} 次，尚无实际大跌样本` : '等待行情数据和对账结果'}</p><p className="design-caption mt-1.5">{risk?.n ? `另有 ${risk.fp} 次预警了但没跌（虚惊一场）` : '暂时无法判断预警效果'}</p>{groupPicker(risks,risk,setRiskKey)}</section>
      <section className="design-card"><div className="design-caption">等待对账</div><div className="track-record-number num">{summary.pending + summary.awaiting_data}<span className="ml-2 text-[13px] text-t-text3">条</span></div><p className="text-[13px] text-t-text2">{waiting ? pendingText(waiting) : '暂未提供下次对账时间'}</p><p className="design-caption mt-1.5">结果出来前不计入命中率</p></section>
    </div>
    <CumulativeChart data={data} group={direction} />
    <section className="design-card"><div className="mb-3 flex flex-wrap items-baseline gap-2"><h2 className="text-sm font-semibold">大跌预警的对错</h2><span className="design-caption">大跌指 {horizon} 个交易日内最大回撤 ≥ {formatRatio(metadata.drawdown_threshold)}</span></div><div className="track-record-cells">{[
      { label: '预警了，真跌了', count: risk?.tp, detail: '提前提醒成功', color: 'var(--fin-success)', background: 'color-mix(in srgb, var(--fin-success) 10%, transparent)' },
      { label: '预警了，没跌（虚惊一场）', count: risk?.fp, detail: '预警未发生', color: 'var(--t-amber)', background: 'var(--t-amber-soft)' },
      { label: '没预警，真跌了（漏报）', count: risk?.fn, detail: '最需要改进的部分', color: 'var(--fin-danger)', background: 'color-mix(in srgb, var(--fin-danger) 10%, transparent)' },
      { label: '没预警，也没跌', count: risk?.tn, detail: '正常排除', color: 'var(--t-text-2)', background: 'var(--t-bg-2)' },
    ].map((cell) => <div className="track-record-cell" key={cell.label} style={{ background: cell.background }}><strong style={{ color: cell.color }}>{cell.label}</strong><div className="num">{cell.count ?? '暂无'}</div><p className="design-caption">{cell.detail}</p></div>)}</div></section>
    <section className="design-card !p-0 overflow-hidden" aria-busy={loading}><div className="px-[18px] pb-2 pt-3.5"><h2 className="text-sm font-semibold">每一条预测</h2><p className="design-caption mt-1">点开可看当时的依据和对账用的行情</p>{filterControls && <div className="mt-3">{filterControls}</div>}</div>
      {pageError && <p role="status" className="px-[18px] py-2 text-sm text-t-down">读取失败，仍显示上次成功加载的记录。</p>}
      {records.length ? <div className="overflow-x-auto"><table className="design-table"><thead><tr><th>发布日</th><th>标的</th><th>预测</th><th>信心</th><th>实际</th><th>结果</th></tr></thead><tbody>{records.map((record) => <RecordRow key={record.id} record={record} expanded={expanded === record.id} onToggle={() => setExpanded(expanded === record.id ? null : record.id)} source={metadata.source} />)}</tbody></table></div> : <div className="design-empty">{summary.opportunities ? '当前筛选下暂无记录。' : '还没有预测记录，首次发布后会在这里更新。'}</div>}
      <div className="flex items-center justify-between gap-3 border-t border-t-divider px-[18px] py-2.5"><p className="design-caption" data-testid="prediction-page-range">{records.length ? `第 ${offset+1}–${offset+records.length} 条，共 ${total} 条` : `共 ${total} 条记录`}</p><nav className="flex gap-1" aria-label="预测明细分页"><button type="button" className="design-ghost" aria-label="上一页预测明细" disabled={loading || offset === 0 || !onPageChange} onClick={() => onPageChange?.(Math.max(0,offset-(pagination?.limit||50)))}><ChevronLeft size={15}/></button><button type="button" className="design-ghost" aria-label="下一页预测明细" disabled={loading || !pagination?.has_more || !onPageChange} onClick={() => onPageChange?.(offset+(pagination?.limit||50))}><ChevronRight size={15}/></button></nav></div>
    </section>
    <details className="design-card !p-0"><summary className="flex cursor-pointer items-center gap-2 px-[18px] py-3.5 text-sm font-semibold"><ChevronDown size={15}/>规则是怎么定的<span className="design-caption font-normal">样本、对账方式、版本</span></summary><div className="space-y-3 px-[18px] pb-4 text-[13px] leading-7 text-t-text2">
      <p>{metadata.frequency === 'trading_day' ? '每个交易日' : '按发布计划'}对 {data.universe.tickers.length} 只美股发布预测，用 {horizon} 个交易日的实际行情对账。{metadata.collection_start_et && metadata.collection_deadline_et ? `美东 ${metadata.collection_start_et} 开始，${metadata.collection_deadline_et} 截止发布。` : ''}</p>
      <p>方向预测：{horizon} 个交易日后涨还是跌。涨幅超过 {formatRatio(metadata.direction_threshold)} 算上涨，跌幅超过相同阈值算下跌，其余为横盘。</p><p>起点价为发布后第一个交易日的开盘价，终点价为第 {horizon} 个交易日收盘价。涨跌幅用终点价除以起点价后减一计算；现金分红不计入。最大回撤比较起点价与随后收盘价相对此前高点的降幅。</p>
      <p>滚动评价窗口可能重叠，记录并非独立样本。{metadata.min_sample_size != null ? `同一模型版本少于 ${metadata.min_sample_size} 条已对账记录时，记录还太少，结论不可靠。` : '记录太少时，不能据此推断未来表现。'}不同模型和版本分别显示，不挑选较高成绩。</p>
      <p>最近发布日：{coverage.batch_date || '暂无'}。实际发布 {coverage.accepted} 条，应发布 {coverage.expected} 条。累计发布失败 {summary.failed} 条；当天没按时发布 {summary.missed} 条，不计入命中率；模型选择不预测 {summary.abstained} 条。</p>
      {unconfirmed.length > 0 && <section data-testid="direction-unconfirmed-models"><h3 className="font-medium">模型未确认的记录，单独统计</h3>{unconfirmed.map((group) => <p key={`${group.prediction_type}:${groupKey(group)}`}>{modelName(group)} · {group.prediction_type === 'direction' ? '方向预测' : '大跌预警'} · 已对账 {group.n} 次，猜中 {group.hits} 次</p>)}</section>}
      <div className="space-y-2">{sortGroups(data.groups).map((group) => <div key={`${group.prediction_type}:${groupKey(group)}`} data-testid="prediction-model-group" data-confirmed={group.model_confirmed}><p>使用的模型：{modelName(group)} · {group.model_confirmed ? '实际模型已确认' : '实际模型尚未确认，单独统计'} · {group.prediction_type === 'direction' ? '方向预测' : '大跌预警'}</p><p className="num design-caption">提示词 {versionLabel(group.prompt_version)} · 策略 {versionLabel(group.strategy_version)} · 评分规则 {versionLabel(group.scorer_version)}</p></div>)}</div>
      <p>交易日历版本：{versionLabel(metadata.calendar_version)}；当前评分规则：{versionLabel(metadata.scorer_version)}。</p><p>固定样本：{data.universe.tickers.join('、') || '暂无'}。样本版本：{versionLabel(data.universe.version)}。行情来源：{sourceDisplayName(metadata.source)}。</p>
    </div></details>
  </div>;
}
function RecordRow({ record, expanded, onToggle, source }: { record: PredictionRecord; expanded: boolean; onToggle: () => void; source: string }) {
  const settled = record.status === 'settled' && record.outcome;
  const result = outcomeLabel(record);
  const success = settled && record.outcome?.hit;
  return <><tr data-testid="prediction-record-row"><td className="num">{dateOnly(record.batch_date)}</td><td className="num font-medium"><button type="button" className="inline-flex items-center gap-1 text-t-accent" aria-expanded={expanded} onClick={onToggle}>{record.ticker}<ChevronDown size={13}/></button></td><td>{predictionLabel(record)}</td><td className="num">{confidence(record)}</td><td className={settled ? 'num' : 'design-caption'}>{settled ? record.prediction_type === 'direction' ? `${directionLabel(record.outcome!.actual_direction)} ${formatRatio(record.outcome!.return_pct)}` : `最大回撤 ${formatRatio(record.outcome!.max_drawdown)}` : record.status === 'pending' ? `${dateOnly(record.window_end)} 对账` : '暂无评分'}</td><td><span className="design-tag" style={settled ? { color: success ? 'var(--fin-success)' : 'var(--fin-danger)', background: success ? 'color-mix(in srgb, var(--fin-success) 10%, transparent)' : 'color-mix(in srgb, var(--fin-danger) 10%, transparent)' } : undefined}>{result}</span></td></tr>{expanded && <tr><td colSpan={6} className="!whitespace-normal bg-t-bg"><BenchmarkRecordDetail record={record} source={source}/></td></tr>}</>;
}

export function BenchmarkTrackRecordView({ shareLink = false }: { shareLink?: boolean }) {
  const [searchParams] = useSearchParams();
  const [filters, setFilters] = useState<TrackRecordFilters>(() => ({ ticker: searchParams.get('ticker') || undefined }));
  const [days, setDays] = useState<number | undefined>(84);
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [result, setResult] = useState<{ key: string; data: PredictionTrackRecord } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const { ticker, status, prediction_type: type } = filters;
  const queryKey=JSON.stringify([ticker,status,type,days]);
  const data=result?.key===queryKey?result.data:null;
  useEffect(() => { const controller=new AbortController();setLoading(true);setError(false);
    apiClient.getPredictionTrackRecord(20,offset,controller.signal,{ticker,status,prediction_type:type,days}).then((value)=>{if(!controller.signal.aborted)setResult({key:queryKey,data:value});}).catch(()=>{if(!controller.signal.aborted)setError(true);}).finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return()=>controller.abort();
  },[ticker,status,type,days,offset,queryKey,refresh]);
  const changeFilters=(next:TrackRecordFilters)=>{setFilters(next);setOffset(0);};
  const controls=<div className="flex flex-wrap gap-3"><label className="design-caption">标的 <select aria-label="标的筛选" className="design-ghost" value={ticker||''} onChange={(event)=>changeFilters({...filters,ticker:event.target.value||undefined})}><option value="">全部标的</option>{result?.data.universe.tickers.map((symbol)=><option key={symbol}>{symbol}</option>)}</select></label><label className="design-caption">状态 <select aria-label="状态筛选" className="design-ghost" value={status||''} onChange={(event)=>changeFilters({...filters,status:event.target.value||undefined})}><option value="">全部状态</option>{recordStatuses.map((value)=><option key={value} value={value}>{statusLabel(value)}</option>)}</select></label><label className="design-caption">预测 <select aria-label="预测类型筛选" className="design-ghost" value={type||''} onChange={(event)=>changeFilters({...filters,prediction_type:event.target.value as 'direction'|'drawdown'||undefined})}><option value="">全部预测</option><option value="direction">方向预测</option><option value="drawdown">大跌预警</option></select></label></div>;
  return <div className="flex flex-col gap-5" data-testid="us20-track-record"><header className="track-record-header"><div className="min-w-0 flex-1"><h1>预测战绩</h1><p>{data ? `${data.metadata.frequency === 'trading_day' ? '每个交易日' : '按发布计划'}对 ${data.universe.tickers.length} 只美股发布预测，${data.metadata.horizon_sessions} 个交易日后核对方向和回撤。猜错的也保留。` : '记录发布时的判断，等待实际行情到期对账，猜错的也保留。'}</p></div><div className="flex items-center gap-2"><div className="design-segments" role="group" aria-label="时间范围">{[{label:'近4周',value:28},{label:'近12周',value:84},{label:'全部',value:undefined}].map((item)=><button type="button" key={item.label} className={`design-segment ${days===item.value?'on':''}`} onClick={()=>{setDays(item.value);setOffset(0);}}>{item.label}</button>)}</div><button type="button" className="design-ghost !px-2" aria-label="刷新战绩" disabled={loading} onClick={()=>setRefresh(v=>v+1)}><RefreshCw size={15} className={loading?'animate-spin':''}/></button>{shareLink&&<a href="/track-record" className="design-caption">查看公开战绩</a>}</div></header>
    {error&&!data&&<p role="alert" className="design-card text-sm text-t-down">战绩暂时无法读取，请点击刷新重试。</p>}{loading&&!data&&<div className="design-empty" role="status">正在加载预测记录…</div>}
    {data&&<TrackRecordContent data={data} loading={loading} pageError={error} filterControls={controls} onPageChange={setOffset}/>}
  </div>;
}
