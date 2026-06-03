import React, { useState } from 'react';
import { apiClient } from '../../api/client';
import { Button } from '../ui/Button';
import { Input } from '../ui/Input';
import { BacktestEquityChart } from './BacktestEquityChart';
import { BacktestTradesTable } from './BacktestTradesTable';

const STRATEGY_OPTIONS: Array<{ value: BacktestStrategy; label: string }> = [
  { value: 'ma_cross', label: 'MA Cross 双均线' },
  { value: 'macd', label: 'MACD' },
  { value: 'rsi_mean_reversion', label: 'RSI 均值回归' },
];

type BacktestStrategy = 'ma_cross' | 'macd' | 'rsi_mean_reversion';

/** 数值型指标格式化：百分比补 %，大额净值用本地千分位。 */
function fmtMetric(value: unknown, suffix = ''): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return '-';
  const rounded = Math.abs(n) >= 1000 ? n.toLocaleString(undefined, { maximumFractionDigits: 0 }) : n.toFixed(2);
  return `${rounded}${suffix}`;
}

export const BacktestPanel: React.FC = () => {
  const [ticker, setTicker] = useState('AAPL');
  const [strategy, setStrategy] = useState<BacktestStrategy>('ma_cross');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);

  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      const payload = await apiClient.runBacktest({
        ticker: ticker.trim().toUpperCase(),
        strategy,
        initial_cash: 100000,
        t_plus_one: true,
      });
      if (!payload.success) {
        setResult(null);
        setError(payload.error || '回测失败');
      } else {
        setResult(payload as unknown as Record<string, unknown>);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : '回测失败');
      setResult(null);
    } finally {
      setLoading(false);
    }
  };

  const metrics = (result?.metrics || {}) as Record<string, unknown>;
  const equityCurve = (result?.equity_curve as Array<Record<string, unknown>>) || [];
  const trades = (result?.trades as Array<Record<string, unknown>>) || [];
  const settings = (result?.settings || {}) as Record<string, unknown>;
  const period = (result?.period || {}) as Record<string, unknown>;
  const initialCash = Number(settings.initial_cash) || 100000;

  return (
    <section className="rounded-xl border border-fin-border bg-fin-card p-4">
      <div className="mb-3 flex flex-wrap items-end gap-3">
        <Input label="Ticker" value={ticker} onChange={(event) => setTicker(event.target.value)} className="min-w-[160px]" />
        <div>
          <label className="mb-1 block text-xs text-fin-muted">策略</label>
          <select
            className="rounded-lg border border-fin-border bg-fin-bg px-3 py-2 text-sm text-fin-text"
            value={strategy}
            onChange={(event) => setStrategy(event.target.value as BacktestStrategy)}
          >
            {STRATEGY_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>
        <Button variant="primary" onClick={run} disabled={loading}>
          {loading ? '回测中...' : '运行回测'}
        </Button>
      </div>

      {error && <p className="mb-3 text-xs text-fin-danger">{error}</p>}

      {result && (
        <div className="space-y-4">
          {/* 核心指标 */}
          <div className="grid gap-2 text-sm md:grid-cols-2 lg:grid-cols-4">
            <MetricCard label="总收益" value={fmtMetric(metrics.total_return_pct, '%')} positive={Number(metrics.total_return_pct) >= 0} />
            <MetricCard label="最大回撤" value={fmtMetric(metrics.max_drawdown_pct, '%')} positive={false} />
            <MetricCard label="交易次数" value={fmtMetric(metrics.trade_count)} />
            <MetricCard label="胜率" value={fmtMetric(metrics.win_rate_pct, '%')} />
          </div>

          {/* 收益曲线 */}
          <div>
            <div className="mb-1.5 flex items-center justify-between text-xs">
              <span className="font-semibold text-fin-text-secondary">组合净值曲线</span>
              {Boolean(period.start && period.end) && (
                <span className="text-2xs text-fin-muted">
                  {String(period.start)} ~ {String(period.end)} · {String(period.bars ?? '')} bars
                </span>
              )}
            </div>
            <BacktestEquityChart equityCurve={equityCurve} initialCash={initialCash} />
          </div>

          {/* 逐笔成交 */}
          <div>
            <div className="mb-1.5 text-xs font-semibold text-fin-text-secondary">逐笔成交记录</div>
            <BacktestTradesTable trades={trades} />
          </div>
        </div>
      )}
    </section>
  );
};

const MetricCard: React.FC<{ label: string; value: string; positive?: boolean }> = ({ label, value, positive }) => {
  const valueColor = positive === undefined ? 'text-fin-text' : positive ? 'text-fin-success' : 'text-fin-danger';
  return (
    <div className="rounded-lg border border-fin-border bg-fin-bg p-3">
      <div className="text-xs text-fin-muted">{label}</div>
      <div className={`text-base font-semibold ${valueColor}`}>{value}</div>
    </div>
  );
};

export default BacktestPanel;
