import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReactECharts from 'echarts-for-react';
import { Calculator, Loader2, TriangleAlert } from 'lucide-react';

import { apiClient } from '../../api/client';
import type {
  PortfolioAttributionResponse,
  PortfolioSummaryResponse,
} from '../../api/contracts';
import { useChartTheme } from '../../hooks/useChartTheme';
import { Card } from '../ui/Card';
import { buildAttributionPositions } from './attributionUtils';


interface AttributionPanelProps {
  data: PortfolioSummaryResponse | null;
  loading: boolean;
}


const formatPct = (value: number | null | undefined, digits = 2) => (
  value === null || value === undefined || !Number.isFinite(value)
    ? '--'
    : `${value >= 0 ? '+' : ''}${value.toFixed(digits)}%`
);


export function AttributionPanel({ data, loading }: AttributionPanelProps) {
  const theme = useChartTheme();
  const positions = useMemo(() => buildAttributionPositions(data), [data]);
  const signature = useMemo(
    () => positions.map((position) => `${position.ticker}:${position.weight.toFixed(8)}`).join('|'),
    [positions],
  );
  const [lookbackDays, setLookbackDays] = useState(252);
  const [result, setResult] = useState<PortfolioAttributionResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [calculating, setCalculating] = useState(false);
  const hasCalculatedRef = useRef(false);

  const calculate = useCallback(async () => {
    if (positions.length === 0) return;
    setCalculating(true);
    setError(null);
    try {
      const next = await apiClient.calculatePortfolioAttribution(positions, lookbackDays);
      setResult(next);
      hasCalculatedRef.current = true;
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : '组合归因计算失败，请稍后重试');
    } finally {
      setCalculating(false);
    }
  }, [lookbackDays, positions]);

  useEffect(() => {
    if (!hasCalculatedRef.current || positions.length === 0) return;
    void calculate();
  }, [calculate, positions.length, signature]);

  const chartOption = useMemo(() => {
    if (!result) return null;
    const items = result.contribution.filter((item) => item.contribution_pct !== null);
    if (items.length === 0) return null;
    return {
      tooltip: {
        trigger: 'axis' as const,
        backgroundColor: theme.tooltipBackground,
        borderColor: theme.tooltipBorder,
        textStyle: { color: theme.tooltipText, fontSize: 11 },
        formatter: (params: Array<{ data: { ticker: string; contribution: number; returnPct: number; weight: number } }>) => {
          const item = params[0]?.data;
          if (!item) return '';
          return `<b>${item.ticker}</b><br/>权重 ${(item.weight * 100).toFixed(1)}%<br/>区间收益 ${formatPct(item.returnPct)}<br/>贡献 ${formatPct(item.contribution)}`;
        },
      },
      grid: { left: 48, right: 14, top: 12, bottom: 28 },
      xAxis: {
        type: 'category' as const,
        data: items.map((item) => item.ticker),
        axisLine: { lineStyle: { color: theme.border } },
        axisLabel: { color: theme.muted, fontSize: 10 },
      },
      yAxis: {
        type: 'value' as const,
        axisLabel: { color: theme.muted, fontSize: 9, formatter: '{value}%' },
        splitLine: { lineStyle: { color: theme.grid, type: 'dashed' } },
      },
      series: [{
        type: 'bar',
        barMaxWidth: 38,
        data: items.map((item) => ({
          value: item.contribution_pct,
          ticker: item.ticker,
          contribution: item.contribution_pct,
          returnPct: item.return_pct,
          weight: item.weight,
          itemStyle: {
            color: (item.contribution_pct ?? 0) >= 0 ? theme.success : theme.danger,
            borderRadius: (item.contribution_pct ?? 0) >= 0 ? [4, 4, 0, 0] : [0, 0, 4, 4],
          },
        })),
        label: {
          show: true,
          position: 'top',
          color: theme.muted,
          fontSize: 9,
          formatter: (params: { value: number }) => formatPct(params.value, 1),
        },
      }],
    };
  }, [result, theme]);

  const factorBeta = result?.factor_exposure.factor_beta ?? {};
  const totalContribution = result?.contribution.reduce(
    (sum, item) => sum + (item.contribution_pct ?? 0),
    0,
  );

  return (
    <Card className="p-4 space-y-3" data-testid="attribution-panel">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-fin-text">组合归因</div>
          <div className="mt-0.5 text-2xs text-fin-muted">区间收益 × 当前持仓权重，基准 SPY</div>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={lookbackDays}
            onChange={(event) => setLookbackDays(Number(event.target.value))}
            className="min-h-9 rounded-lg border border-fin-border bg-fin-bg px-2 text-xs text-fin-text"
            aria-label="归因回看周期"
          >
            <option value={126}>6 个月</option>
            <option value={252}>1 年</option>
            <option value={504}>2 年</option>
          </select>
          <button
            type="button"
            onClick={() => void calculate()}
            disabled={loading || calculating || positions.length === 0}
            className="inline-flex min-h-9 items-center gap-1.5 rounded-lg bg-fin-primary px-3 text-xs font-medium text-white transition-colors hover:bg-fin-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {calculating ? <Loader2 size={14} className="animate-spin" /> : <Calculator size={14} />}
            {result ? '重新计算' : '计算归因'}
          </button>
        </div>
      </div>

      {positions.length === 0 && !loading && (
        <div className="rounded-lg border border-fin-border bg-fin-bg/50 px-3 py-4 text-xs text-fin-muted">
          请先在上方持仓管理中录入股票，再计算组合归因。
        </div>
      )}

      {error && (
        <div className="flex items-start gap-2 rounded-lg border border-fin-danger/40 bg-fin-danger/10 px-3 py-2 text-xs text-fin-danger">
          <TriangleAlert size={14} className="mt-0.5 shrink-0" />
          {error}
        </div>
      )}

      {result && (
        <>
          <div className="grid grid-cols-2 gap-2 xl:grid-cols-4">
            {[
              ['组合 Beta', result.beta?.toFixed(2) ?? '--'],
              ['组合贡献', formatPct(totalContribution)],
              [`基准 ${result.benchmark.symbol}`, formatPct(result.benchmark.return_pct)],
              ['样本截止', result.as_of],
            ].map(([label, value]) => (
              <div key={label} className="rounded-lg border border-fin-border bg-fin-bg/50 px-3 py-2">
                <div className="text-2xs text-fin-muted">{label}</div>
                <div className="mt-1 text-sm font-semibold text-fin-text tabular">{value}</div>
              </div>
            ))}
          </div>

          {chartOption && (
            <ReactECharts
              option={chartOption}
              style={{ width: '100%', height: 230 }}
              opts={{ renderer: 'svg' }}
              notMerge
              lazyUpdate
            />
          )}

          {Object.keys(factorBeta).length > 0 && (
            <div className="flex flex-wrap gap-2 text-2xs">
              {Object.entries(factorBeta).map(([factor, value]) => (
                <span key={factor} className="rounded-md border border-fin-border bg-fin-bg/50 px-2 py-1 text-fin-text-secondary">
                  {factor}: {value === null ? '--' : value.toFixed(2)}
                </span>
              ))}
            </div>
          )}

          {result.warnings.length > 0 && (
            <div className="rounded-lg border border-fin-warning/40 bg-fin-warning/10 px-3 py-2 text-2xs text-fin-warning">
              {result.warnings.map((warning) => <div key={warning}>• {warning}</div>)}
            </div>
          )}
        </>
      )}
    </Card>
  );
}


export default AttributionPanel;
