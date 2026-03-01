import React, { useState } from 'react';
import { apiClient } from '../../api/client';
import { Button } from '../ui/Button';
import { Input } from '../ui/Input';

export const BacktestPanel: React.FC = () => {
  const [ticker, setTicker] = useState('AAPL');
  const [strategy, setStrategy] = useState<'ma_cross' | 'macd' | 'rsi_mean_reversion'>('ma_cross');
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

  return (
    <section className="rounded-xl border border-fin-border bg-fin-card p-4">
      <div className="mb-3 flex flex-wrap items-end gap-3">
        <Input label="Ticker" value={ticker} onChange={(event) => setTicker(event.target.value)} className="min-w-[160px]" />
        <div>
          <label className="mb-1 block text-xs text-fin-muted">策略</label>
          <select
            className="rounded-lg border border-fin-border bg-fin-bg px-3 py-2 text-sm text-fin-text"
            value={strategy}
            onChange={(event) => setStrategy(event.target.value as 'ma_cross' | 'macd' | 'rsi_mean_reversion')}
          >
            <option value="ma_cross">MA Cross</option>
            <option value="macd">MACD</option>
            <option value="rsi_mean_reversion">RSI Mean Reversion</option>
          </select>
        </div>
        <Button variant="primary" onClick={run} disabled={loading}>
          {loading ? '回测中...' : '运行回测'}
        </Button>
      </div>

      {error && <p className="mb-3 text-xs text-red-400">{error}</p>}

      {result && (
        <div className="grid gap-2 text-sm md:grid-cols-2 lg:grid-cols-4">
          <MetricCard label="总收益(%)" value={metrics.total_return_pct} />
          <MetricCard label="最大回撤(%)" value={metrics.max_drawdown_pct} />
          <MetricCard label="交易次数" value={metrics.trade_count} />
          <MetricCard label="胜率(%)" value={metrics.win_rate_pct} />
        </div>
      )}
    </section>
  );
};

const MetricCard: React.FC<{ label: string; value: unknown }> = ({ label, value }) => (
  <div className="rounded-lg border border-fin-border bg-fin-bg p-3">
    <div className="text-xs text-fin-muted">{label}</div>
    <div className="text-base font-semibold text-fin-text">{value == null ? '-' : String(value)}</div>
  </div>
);

export default BacktestPanel;
