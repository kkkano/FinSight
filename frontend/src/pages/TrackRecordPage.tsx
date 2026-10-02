import { useEffect, useState } from 'react';
import { ArrowLeft, Clock3, Info, RefreshCw, Target } from 'lucide-react';
import { Link } from 'react-router-dom';
import { apiClient } from '../api/client';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import type { PredictionGroup, PredictionRecord, PredictionTrackRecord, PredictionType } from '../types/predictions';
import {
  EARLY_SAMPLE_SIZE, agentLabel, directionLabel, formatDelta, formatEtTime,
  formatHitRate, formatRatio, predictionLabel, sortGroups, sortRecentRecords, statusLabel,
} from './trackRecord';

const countFormatter = new Intl.NumberFormat('zh-CN');

function SummaryCard({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <Card className="p-4">
      <div className="text-xs text-fin-muted">{label}</div>
      <div className="mt-2 text-2xl font-semibold tabular-nums text-fin-text">{value}</div>
      <p className="mt-1 text-xs leading-relaxed text-fin-muted">{detail}</p>
    </Card>
  );
}

function GroupCard({ group }: { group: PredictionGroup }) {
  const isRisk = group.prediction_type === 'drawdown';
  const hasResults = group.n > 0;
  return (
    <Card className="min-w-0 p-4" data-testid="prediction-model-group" data-confirmed={group.model_confirmed}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-xs text-fin-muted">{agentLabel(group.agent)}</p>
          <h4 className="mt-1 break-all text-sm font-semibold text-fin-text">{group.actual_model || '未知模型'}</h4>
        </div>
        <span className={`rounded-full border px-2 py-0.5 text-xs ${group.model_confirmed
          ? 'border-fin-border text-fin-muted'
          : 'border-amber-500/30 bg-amber-500/10 text-amber-600 dark:text-amber-400'}`}>
          {group.model_confirmed ? '供应商已确认模型' : '模型身份未确认'}
        </span>
      </div>

      {hasResults ? (
        <>
          <dl className="mt-4 grid grid-cols-2 gap-3">
            <div>
              <dt className="text-xs text-fin-muted">AI 命中率</dt>
              <dd className="mt-1 text-xl font-semibold tabular-nums text-fin-text">{formatHitRate(group.hit_rate, group.n)}</dd>
              <dd className="text-xs text-fin-muted">{group.hits} / {group.n} 命中</dd>
            </div>
            <div>
              <dt className="text-xs text-fin-muted">同样本基准</dt>
              <dd className="mt-1 text-xl font-semibold tabular-nums text-fin-text">{formatHitRate(group.baseline_hit_rate, group.n)}</dd>
              <dd className="text-xs text-fin-muted">{group.baseline_hits} / {group.n} 命中</dd>
            </div>
          </dl>
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-fin-border pt-3 text-xs">
            <span className={group.delta !== null && group.delta < 0 ? 'text-fin-danger' : 'text-fin-text'} data-testid="prediction-baseline-delta">
              AI − 基准：{formatDelta(group.delta, group.n)}
            </span>
            <span className="text-fin-muted">已结算 n = {group.n}{group.n < EARLY_SAMPLE_SIZE ? ' · 样本不足' : ''}</span>
          </div>
          {isRisk ? (
            <div className="mt-4 border-t border-fin-border pt-3">
              <p className="text-xs text-fin-muted">实际事件发生率：{formatRatio((group.tp + group.fn) / group.n)}（{group.tp + group.fn} / {group.n}）</p>
              <dl className="mt-2 grid grid-cols-2 gap-2 text-xs" aria-label="风险混淆计数">
                {[
                  ['TP · 正确预警', group.tp, '预测发生，实际发生'],
                  ['FP · 误报', group.fp, '预测发生，实际未发生'],
                  ['TN · 正确排除', group.tn, '预测不发生，实际未发生'],
                  ['FN · 漏报', group.fn, '预测不发生，实际发生'],
                ].map(([label, count, hint]) => (
                  <div key={label} className="rounded-lg bg-fin-bg p-2">
                    <dt className="text-fin-text-secondary">{label}</dt>
                    <dd className="mt-0.5 font-semibold tabular-nums text-fin-text">{count}</dd>
                    <dd className="mt-0.5 text-fin-muted">{hint}</dd>
                  </div>
                ))}
              </dl>
            </div>
          ) : null}
        </>
      ) : (
        <p className="mt-4 rounded-lg bg-fin-bg px-3 py-4 text-sm text-fin-muted">等待首批结算</p>
      )}

      <dl className="mt-4 space-y-1 border-t border-fin-border pt-3 text-xs text-fin-muted">
        <div className="flex gap-2"><dt className="shrink-0">提示版本</dt><dd className="break-all">{group.prompt_version}</dd></div>
        <div className="flex gap-2"><dt className="shrink-0">策略版本</dt><dd className="break-all">{group.strategy_version}</dd></div>
        <div className="flex gap-2"><dt className="shrink-0">评分版本</dt><dd className="break-all">{group.scorer_version}</dd></div>
      </dl>
    </Card>
  );
}

function TaskResults({ type, data }: { type: PredictionType; data: PredictionTrackRecord }) {
  const groups = sortGroups(data.groups.filter((group) => group.prediction_type === type));
  const confirmed = groups.filter((group) => group.model_confirmed);
  const unconfirmed = groups.filter((group) => !group.model_confirmed);
  const isRisk = type === 'drawdown';
  const title = isRisk ? '5 日回撤事件 · Risk' : '5 日方向 · Technical';
  return (
    <section className="space-y-3" aria-labelledby={`${type}-results-title`} data-testid={`${type}-results`}>
      <div>
        <h2 id={`${type}-results-title`} className="text-base font-semibold text-fin-text">{title}</h2>
        <p className="mt-1 text-xs leading-relaxed text-fin-muted">
          {isRisk
            ? `事件定义：按收盘序列计算的最大回撤 ≥ ${formatRatio(data.metadata.drawdown_threshold)}。基准：始终不发生。`
            : `方向阈值：上涨 > +${formatRatio(data.metadata.direction_threshold)}，下跌 < −${formatRatio(data.metadata.direction_threshold)}，其余为横盘。基准：永远看多。`}
        </p>
      </div>
      {!groups.length ? (
        <Card className="flex items-center gap-2 p-5 text-sm text-fin-muted"><Clock3 size={16} />等待首批结算</Card>
      ) : null}
      {confirmed.length ? (
        <div className="grid gap-3 lg:grid-cols-2">
          {confirmed.map((group) => <GroupCard key={[group.agent, group.actual_model, group.prompt_version, group.strategy_version, group.scorer_version].join('|')} group={group} />)}
        </div>
      ) : null}
      {unconfirmed.length ? (
        <div className="space-y-2 rounded-xl border border-dashed border-fin-border p-3" data-testid={`${type}-unconfirmed-models`}>
          <h3 className="text-sm font-medium text-fin-text">模型身份未确认 · 单独统计</h3>
          <p className="text-xs text-fin-muted">供应商未确认实际模型名称，以下记录不并入已确认模型。</p>
          <div className="grid gap-3 lg:grid-cols-2">
            {unconfirmed.map((group) => <GroupCard key={[group.agent, group.actual_model, group.prompt_version, group.strategy_version, group.scorer_version].join('|')} group={group} />)}
          </div>
        </div>
      ) : null}
    </section>
  );
}

function RecordOutcome({ record }: { record: PredictionRecord }) {
  const outcome = record.outcome;
  if (!outcome || record.status !== 'settled') {
    return (
      <div>
        <span className="text-fin-text-secondary">{statusLabel(record.status)}</span>
        {record.status === 'awaiting_data' || record.status === 'invalid'
          ? <p className="mt-1 text-xs text-fin-muted">保留原窗口，等待同源行情核验。</p>
          : null}
        {record.error_code ? <p className="mt-1 text-xs text-fin-muted">未生成可评分结果，保留此机会。</p> : null}
      </div>
    );
  }
  return (
    <div className="space-y-1 text-xs">
      <p className={outcome.hit ? 'text-fin-success' : 'text-fin-danger'}>已结算 · {outcome.hit ? '命中' : '未命中'}</p>
      <p className="text-fin-text">{record.prediction_type === 'direction'
        ? `实际${directionLabel(outcome.actual_direction)} · 收益 ${formatRatio(outcome.return_pct)}`
        : `实际${outcome.actual_event ? '发生' : '未发生'} · 最大回撤 ${formatRatio(outcome.max_drawdown)}`}</p>
      <p className="text-fin-muted">同样本基准：{outcome.baseline_hit ? '命中' : '未命中'}</p>
      <p className="tabular-nums text-fin-muted">P0 {outcome.p0.toFixed(2)} → P5 {outcome.p5.toFixed(2)}</p>
    </div>
  );
}

export function TrackRecordContent({ data, loading = false, pageError = false, onPageChange }: {
  data: PredictionTrackRecord;
  loading?: boolean;
  pageError?: boolean;
  onPageChange?: (offset: number) => void;
}) {
  const { summary, coverage, universe, metadata } = data;
  const records = sortRecentRecords(data.records);
  const pagination = data.pagination;
  const pageOffset = pagination?.offset ?? 0;
  const pageLimit = pagination?.limit ?? 50;
  const totalRecords = pagination?.total ?? summary.opportunities;
  const coverageRatio = coverage.expected > 0 ? Math.min(1, coverage.accepted / coverage.expected) : 0;
  return (
    <>
      <div className="flex flex-wrap items-center gap-2 text-xs text-fin-muted">
        <span className={`rounded-full border px-2.5 py-1 ${data.enabled ? 'border-fin-primary/30 bg-fin-primary/10 text-fin-primary' : 'border-fin-border'}`}>
          {data.enabled ? '固定采集已启用' : '固定采集尚未启用'}
        </span>
        <span>{universe.version} · {universe.tickers.length} 只美股 · 每日 {universe.tickers.length * 2} 个机会</span>
        <span>行情来源：{metadata.source}</span>
      </div>

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="累计样本概览">
        <SummaryCard label="已结算 · 成熟样本" value={countFormatter.format(summary.settled)} detail="仅已结算记录进入命中率分母" />
        <SummaryCard label="待结算" value={countFormatter.format(summary.pending)} detail={`另有 ${summary.awaiting_data} 条等待行情；不计为命中或未命中`} />
        <SummaryCard label="已接受预测 / 全部机会" value={`${summary.predictions} / ${summary.opportunities}`} detail="失败、错过登记与弃权均保留在覆盖记录中" />
        <SummaryCard label="累计批次 / 涉及股票" value={`${summary.batch_count} / ${summary.stock_count}`} detail="固定样本池观察，不代表全部美股" />
      </section>

      <Card className="p-4" data-testid="prediction-coverage">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-fin-text">最近批次覆盖</h2>
            <p className="mt-1 text-xs text-fin-muted">{coverage.batch_date ? `${coverage.batch_date}（美东交易日）` : '尚无采集批次'} · 已尝试 {coverage.attempts} 次</p>
          </div>
          <div className="text-right">
            <p className="text-xl font-semibold tabular-nums text-fin-text">{coverage.accepted} / {coverage.expected}</p>
            <p className="text-xs text-fin-muted">已接受预测 / 预定机会</p>
          </div>
        </div>
        <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-fin-bg-secondary" role="progressbar"
          aria-label="最近批次预测覆盖" aria-valuemin={0} aria-valuemax={coverage.expected || 40} aria-valuenow={coverage.accepted}>
          <div className="h-full rounded-full bg-fin-primary" style={{ width: `${coverageRatio * 100}%` }} />
        </div>
        <div className="mt-3 flex flex-wrap gap-2 text-xs">
          {Object.entries(coverage.counts).map(([status, count]) => (
            <span key={status} className="rounded-md bg-fin-bg px-2 py-1 text-fin-text-secondary">{statusLabel(status)} {count}</span>
          ))}
          {!Object.keys(coverage.counts).length ? <span className="text-fin-muted">暂无机会状态</span> : null}
        </div>
        <p className="mt-3 text-xs text-fin-muted">累计：预测失败 {summary.failed} · 错过登记 {summary.missed} · 主动弃权 {summary.abstained}。最近进展：{formatEtTime(coverage.last_update)}</p>
      </Card>

      <div className="flex items-start gap-2 rounded-xl border border-fin-border bg-fin-panel p-4 text-xs leading-relaxed text-fin-muted" role="note">
        <Info size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
        <div>
          {!summary.settled ? <p className="mb-1 font-medium text-fin-text">等待首批结算。预测需自然经过 5 个交易日并取得完整行情，才产生真实成绩。</p> : null}
          <p>每组少于 {EARLY_SAMPLE_SIZE} 条成熟记录时标记“样本不足”；这只是阅读提示，不是显著性检验。滚动 5 日窗口存在重叠，记录并非独立样本。</p>
          <p>结果仅描述固定样本中的表现，不代表投资收益或已证明的预测优势。AI 低于基准、未命中及失败记录同样展示。</p>
        </div>
      </div>

      <TaskResults type="direction" data={data} />
      <TaskResults type="drawdown" data={data} />

      <section aria-labelledby="prediction-records-title" aria-busy={loading}>
        <div className="mb-3">
          <h2 id="prediction-records-title" className="text-base font-semibold text-fin-text">机会与预测明细</h2>
          <p className="mt-1 text-xs text-fin-muted">每页 {pageLimit} 条，按批次日期倒序、记录 ID 排列；所有状态使用同一展示规则。上方汇总包含全部公开历史。</p>
        </div>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs text-fin-muted" data-testid="prediction-page-range" aria-live="polite">
            {records.length ? `第 ${pageOffset + 1}–${pageOffset + records.length} 条，共 ${totalRecords} 条` : `共 ${totalRecords} 条记录`}
            {loading ? ' · 正在加载…' : ''}
          </p>
          <nav className="flex gap-2" aria-label="预测明细分页">
            <Button type="button" size="sm" disabled={loading || pageOffset === 0 || !onPageChange}
              onClick={() => onPageChange?.(Math.max(0, pageOffset - pageLimit))}>上一页</Button>
            <Button type="button" size="sm" disabled={loading || !pagination?.has_more || !onPageChange}
              onClick={() => onPageChange?.(pageOffset + pageLimit)}>下一页</Button>
          </nav>
        </div>
        {pageError ? <p role="status" className="mb-3 text-xs text-fin-danger">读取失败，仍显示上次成功加载的记录。请重试翻页或刷新。</p> : null}
        {!records.length ? (
          <Card className="p-8 text-center text-sm text-fin-muted">尚无前瞻预测记录。真实战绩将从首次采集开始累积。</Card>
        ) : (
          <Card className="overflow-hidden">
            <div className="overflow-x-auto" role="region" aria-label="预测明细，可横向滚动" tabIndex={0}>
              <table className="min-w-[1060px] w-full text-left text-sm" data-testid="prediction-records-table">
                <thead className="border-b border-fin-border bg-fin-bg text-xs text-fin-muted">
                  <tr>
                    {['标的 / 批次', '任务 / 实际模型', '预先判断', '状态 / 实际结果', '依据与追溯'].map((label) => <th key={label} scope="col" className="px-4 py-3 font-medium">{label}</th>)}
                  </tr>
                </thead>
                <tbody className="divide-y divide-fin-border">
                  {records.map((record) => (
                    <tr key={record.id} data-testid="prediction-record-row" className="align-top hover:bg-fin-bg-secondary/40">
                      <td className="px-4 py-3">
                        <p className="font-semibold text-fin-text">{record.ticker}</p>
                        <p className="mt-1 text-xs text-fin-muted">批次 {record.batch_date}</p>
                        <p className="mt-1 whitespace-nowrap text-xs text-fin-muted">{record.window_start.slice(0, 10)} → {record.window_end.slice(0, 10)}</p>
                      </td>
                      <td className="max-w-[210px] px-4 py-3">
                        <p className="text-fin-text">{record.prediction_type === 'direction' ? '方向' : '回撤事件'} · {record.agent === 'technical' ? 'Technical' : 'Risk'}</p>
                        <p className="mt-1 break-all text-xs text-fin-muted">{record.actual_model || '未知模型'}</p>
                        {!record.model_confirmed ? <p className="mt-1 text-xs text-amber-600 dark:text-amber-400">模型身份未确认</p> : null}
                      </td>
                      <td className="px-4 py-3 text-fin-text">{predictionLabel(record)}</td>
                      <td className="min-w-[220px] px-4 py-3"><RecordOutcome record={record} /></td>
                      <td className="max-w-[280px] px-4 py-3 text-xs">
                        <p className="leading-relaxed text-fin-text-secondary">{record.reason || '未形成有效预测依据'}</p>
                        <details className="mt-2 text-fin-muted">
                          <summary className="cursor-pointer text-fin-primary">查看证据与时间</summary>
                          <dl className="mt-2 space-y-1 break-words">
                            <div><dt className="inline">预测发布：</dt><dd className="inline">{formatEtTime(record.issued_at)}</dd></div>
                            <div><dt className="inline">提示版本：</dt><dd className="inline">{record.prompt_version}</dd></div>
                            <div><dt className="inline">输入证据：</dt><dd className="inline">{record.evidence_refs.length ? record.evidence_refs.join('、') : '无'}</dd></div>
                            {record.outcome ? <div><dt className="inline">结算时间：</dt><dd className="inline">{formatEtTime(record.outcome.settled_at)}</dd></div> : null}
                          </dl>
                        </details>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}
      </section>

      <Card className="p-4">
        <details>
          <summary className="cursor-pointer text-sm font-medium text-fin-text">评分口径与固定样本池</summary>
          <div className="mt-3 space-y-3 text-xs leading-relaxed text-fin-muted">
            <p>P0 为预测发布后预定首个常规交易时段的开盘价；P5 为包含起始日在内第 5 个交易日的收盘价。方向收益 = P5 / P0 − 1，阈值相等时归为横盘。</p>
            <p>回撤使用 P0 与随后 5 个收盘价构成的序列，计算价格相对此前运行高点的最大降幅；不用日内最低价或期末跌幅代替。现金分红不计入收益。</p>
            <p>两类任务分别以完全相同的已结算记录对照各自基准，不合并为 Agent 总排行榜。提示、策略或实际模型变化后分组展示；旧版本保留。</p>
            <p>每日美东 08:45 开始、09:20 截止登记；每只股票 2 个机会。未按时形成有效判断的机会保留为失败、弃权或错过登记，不能事后补写。</p>
            <div>
              <p className="mb-2 text-fin-text">固定样本池 · {universe.version}</p>
              <div className="flex flex-wrap gap-1.5">{universe.tickers.map((ticker) => <span key={ticker} className="rounded border border-fin-border px-2 py-0.5 font-mono">{ticker}</span>)}</div>
            </div>
          </div>
        </details>
      </Card>
    </>
  );
}

export function TrackRecordPage() {
  const [data, setData] = useState<PredictionTrackRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [offset, setOffset] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(false);
    apiClient.getPredictionTrackRecord(50, offset, controller.signal).then((response) => {
      if (!controller.signal.aborted) setData(response);
    }).catch(() => {
      if (!controller.signal.aborted) setError(true);
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [offset, refresh]);

  return (
    <main id="main-content" className="h-screen overflow-y-auto bg-fin-bg px-4 py-6 md:px-8">
      <div className="mx-auto max-w-7xl space-y-6">
        <header className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="mb-2 flex items-center gap-2 text-xs font-medium text-fin-primary"><Target size={16} />FinSight · 公开只读账本</p>
            <h1 className="text-2xl font-semibold text-fin-text">预测战绩</h1>
            <p className="mt-2 max-w-2xl text-sm leading-relaxed text-fin-muted">Technical 与 Risk 对固定美股样本的 5 日前瞻预测。方向与回撤事件分别评价，保留每次机会及结果。</p>
          </div>
          <div className="flex items-center gap-2">
            <Link to="/welcome" className="inline-flex min-h-10 items-center gap-1.5 rounded-lg border border-fin-border px-3 text-sm text-fin-text-secondary transition-colors hover:bg-fin-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-fin-primary/50"><ArrowLeft size={15} />返回 FinSight</Link>
            <Button type="button" onClick={() => setRefresh((value) => value + 1)} disabled={loading} aria-label="刷新战绩">
              <RefreshCw size={15} className={loading ? 'animate-spin' : ''} />{loading ? '加载中' : '刷新'}
            </Button>
          </div>
        </header>
        {error ? <div role="alert" className="rounded-xl border border-fin-danger/30 bg-fin-danger/5 p-4 text-sm text-fin-danger">战绩数据暂时无法读取，请点击刷新重试。{data ? '下方保留上一次成功加载的数据。' : ''}</div> : null}
        {loading && !data ? <Card className="p-10 text-center text-sm text-fin-muted" role="status">正在读取公开预测账本…</Card> : null}
        {data ? <TrackRecordContent data={data} loading={loading} pageError={error} onPageChange={(nextOffset) => {
          setOffset(nextOffset);
          setRefresh((value) => value + 1);
        }} /> : null}
      </div>
    </main>
  );
}
