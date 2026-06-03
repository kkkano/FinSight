/**
 * P2-7：LLM 成本审计面板。
 *
 * 展示最近 N 天的 LLM 调用成本：汇总卡片 + 每日趋势图（成本/token 双轴）+ Top 消耗请求表格。
 * 数据源 GET /api/system/cost-audit?days=N（需内部 API key 或已登录身份）。
 *
 * 设计：颜色全部走 fin-* token，图表用 useChartTheme（亮暗同构）。
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import ReactECharts from 'echarts-for-react';

import { apiClient } from '../api/client';
import { useChartTheme } from '../hooks/useChartTheme';
import {
  EMPTY_COST_AUDIT,
  buildDailyCostOption,
  formatCompactNumber,
  formatDateTime,
  formatUsd,
  normalizeCostAudit,
  sourceLabel,
  type CostAuditData,
} from './costAudit';

const DAYS_OPTIONS = [7, 14, 30] as const;

const SummaryCard: React.FC<{ title: string; value: string; hint?: string }> = ({ title, value, hint }) => (
  <section className="rounded-2xl border border-fin-border bg-fin-card p-4 shadow-sm">
    <div className="text-xs text-fin-muted">{title}</div>
    <div className="mt-1 text-2xl font-semibold text-fin-text">{value}</div>
    {hint ? <div className="mt-1 text-xs text-fin-muted">{hint}</div> : null}
  </section>
);

export const CostAuditPage: React.FC = () => {
  const chartTheme = useChartTheme();
  const [days, setDays] = useState<number>(7);
  const [data, setData] = useState<CostAuditData>(EMPTY_COST_AUDIT);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async (nextDays: number) => {
    setLoading(true);
    setError('');
    try {
      const response = await apiClient.getCostAudit(nextDays);
      setData(normalizeCostAudit(response));
    } catch (fetchError) {
      setError(fetchError instanceof Error ? fetchError.message : '加载成本审计数据失败');
      setData(EMPTY_COST_AUDIT);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(days);
  }, [days, load]);

  const dailyOption = useMemo(
    () => buildDailyCostOption(data.daily, chartTheme),
    [data.daily, chartTheme],
  );

  const hasDaily = data.daily.length > 0;

  return (
    <main id="main-content" className="h-screen overflow-y-auto bg-fin-bg px-4 py-6 md:px-8">
      <div className="mx-auto max-w-7xl space-y-6">
        <header className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold text-fin-text">成本审计</h1>
            <p className="text-sm text-fin-muted">LLM 调用 token 与成本持久化审计 · 最近 {days} 天</p>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1 rounded-md border border-fin-border p-1">
              {DAYS_OPTIONS.map((option) => {
                const active = option === days;
                return (
                  <button
                    key={option}
                    type="button"
                    onClick={() => setDays(option)}
                    className={[
                      'rounded px-3 py-1 text-sm font-medium transition-colors',
                      active ? 'bg-fin-primary text-white' : 'text-fin-text hover:bg-fin-bg-secondary',
                    ].join(' ')}
                    aria-pressed={active}
                  >
                    {option}天
                  </button>
                );
              })}
            </div>
            <Link to="/rag-inspector" className="rounded-md border border-fin-border px-3 py-2 text-sm text-fin-text hover:bg-fin-bg-secondary">
              RAG Inspector
            </Link>
            <button
              type="button"
              onClick={() => void load(days)}
              className="rounded-md bg-fin-primary px-3 py-2 text-sm font-medium text-white hover:opacity-90"
            >
              刷新
            </button>
          </div>
        </header>

        {error ? (
          <div className="rounded-xl border border-red-400/40 bg-red-500/10 px-4 py-3 text-sm text-red-200">{error}</div>
        ) : null}

        <section className="grid gap-4 md:grid-cols-3">
          <SummaryCard
            title={`${days} 天总成本`}
            value={formatUsd(data.total_cost_usd)}
            hint={data.total_cost_usd === 0 ? '部分模型单价未配置（仅统计 token）' : undefined}
          />
          <SummaryCard title={`${days} 天总 Token`} value={formatCompactNumber(data.total_tokens)} hint={`${data.total_tokens.toLocaleString()} tokens`} />
          <SummaryCard title={`${days} 天请求数`} value={String(data.request_count)} hint="已落库的 LLM 请求" />
        </section>

        <section className="rounded-2xl border border-fin-border bg-fin-card p-4 shadow-sm">
          <div className="mb-3 flex items-center justify-between gap-3">
            <h2 className="text-sm font-semibold text-fin-text">每日成本趋势</h2>
            {loading ? <span className="text-xs text-fin-muted">加载中…</span> : null}
          </div>
          {hasDaily ? (
            <ReactECharts option={dailyOption} style={{ width: '100%', height: 320 }} notMerge opts={{ renderer: 'svg' }} />
          ) : (
            <div className="flex h-40 items-center justify-center text-sm text-fin-muted">暂无成本数据</div>
          )}
        </section>

        <section className="rounded-2xl border border-fin-border bg-fin-card p-4 shadow-sm">
          <h2 className="mb-3 text-sm font-semibold text-fin-text">Top 消耗请求</h2>
          {data.top_requests.length === 0 ? (
            <div className="flex h-24 items-center justify-center text-sm text-fin-muted">暂无请求记录</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-fin-border text-sm">
                <thead>
                  <tr className="text-left text-xs uppercase tracking-wide text-fin-muted">
                    <th className="px-3 py-2 font-medium">时间</th>
                    <th className="px-3 py-2 font-medium">来源</th>
                    <th className="px-3 py-2 font-medium">Session</th>
                    <th className="px-3 py-2 text-right font-medium">Token</th>
                    <th className="px-3 py-2 text-right font-medium">LLM 调用</th>
                    <th className="px-3 py-2 text-right font-medium">成本</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-fin-border/80">
                  {data.top_requests.map((req) => (
                    <tr key={req.id} className="align-top hover:bg-fin-bg-secondary/60">
                      <td className="px-3 py-2 text-fin-muted">{formatDateTime(req.created_at)}</td>
                      <td className="px-3 py-2">
                        <span className="rounded-full border border-fin-border px-2 py-0.5 text-xs text-fin-text">{sourceLabel(req.source)}</span>
                      </td>
                      <td className="max-w-[220px] truncate px-3 py-2 font-mono text-xs text-fin-text" title={req.session_id}>{req.session_id}</td>
                      <td className="px-3 py-2 text-right font-medium text-fin-text">{req.total_tokens.toLocaleString()}</td>
                      <td className="px-3 py-2 text-right text-fin-muted">{req.llm_calls}</td>
                      <td className="px-3 py-2 text-right text-fin-text">{formatUsd(req.cost_usd)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </main>
  );
};

export default CostAuditPage;
