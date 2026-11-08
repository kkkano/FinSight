import { useEffect, useMemo, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { Link } from 'react-router-dom';
import { apiClient } from '../../api/client';
import { useDashboardData } from '../../hooks/useDashboardData';
import { exchangeDisplayName, useCompanyProfile } from '../../hooks/useCompanyProfile';
import { useStore } from '../../store/useStore';
import type { KlineData } from '../../types';
import type { ResearchPriceLevel } from '../../types/runtime';
import { parseQuotePayload, type ParsedQuote } from '../../utils/quote';
import { sourceDisplayName } from '../../utils/sourceDisplayName';
import EChart from '../charts/EChart';
import { CHART_RANGES, selectChartRange, type ChartRange } from './chartRange';
import { buildKlineSmartChartData } from '../SmartChart';
import { buildContextChart, movingAverage20 } from './contextChart';
import styles from './RightPanelDesign.module.css';

const number = (value: unknown): number | undefined => typeof value === 'number' && Number.isFinite(value) ? value : undefined;
const price = (value: number) => value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const largeNumber = (value: number) => Math.abs(value) >= 1e12 ? `${(value / 1e12).toFixed(2)} 万亿`
  : Math.abs(value) >= 1e8 ? `${(value / 1e8).toFixed(2)} 亿` : value.toLocaleString('zh-CN');

export function RightPanelMarket({ symbol, priceLevels = [] }: { symbol: string; priceLevels?: ResearchPriceLevel[] }) {
  const dark = useStore((state) => state.theme === 'dark');
  const convention = useStore((state) => state.colorConvention);
  const owner = useStore((state) => state.authIdentity?.userId);
  const { asset, dashboardData } = useDashboardData(symbol);
  const companyProfile = useCompanyProfile(symbol).data;
  const [rows, setRows] = useState<KlineData[]>([]);
  const [quote, setQuote] = useState<ParsedQuote>({});
  const [source, setSource] = useState('');
  const [asOf, setAsOf] = useState('');
  const [dataKind, setDataKind] = useState('');
  const [currency, setCurrency] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);
  const [range, setRange] = useState<ChartRange>('3m');
  const [line, setLine] = useState(false);
  const [hasPrediction, setHasPrediction] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setRows([]); setQuote({}); setSource(''); setAsOf(''); setDataKind(''); setCurrency(''); setError(''); setLoading(true);
    void Promise.allSettled([apiClient.fetchKline(symbol, '1y', '1d', controller.signal),
      apiClient.fetchStockPrice(symbol, controller.signal)]).then(([history, current]) => {
      if (controller.signal.aborted) return;
      if (history.status === 'fulfilled') {
        const data = history.value.data;
        const values = (data?.kline_data ?? []).filter((row) => [row.open, row.close, row.high, row.low].every((value) => number(value) !== undefined));
        setRows(values);
        setSource(data?.source || data?.provider || '');
        setAsOf(data?.as_of || values.at(-1)?.time || '');
        setDataKind('daily_close');
        setCurrency(data?.currency || '');
        if (!values.length) setError(data?.error || '该标的暂无可用的历史行情。');
      } else setError('行情数据读取失败，请重试。');
      if (current.status === 'fulfilled') {
        const envelope = current.value.data;
        const latest = parseQuotePayload(envelope);
        setQuote(latest);
        if (latest.price !== undefined) {
          setSource(envelope.source || envelope.provider || '');
          setAsOf(envelope.as_of || '');
          setDataKind(envelope.data_kind || 'unknown');
          setCurrency(envelope.currency || '');
        }
      }
      setLoading(false);
    });
    return () => controller.abort();
  }, [symbol, attempt]);

  useEffect(() => {
    setHasPrediction(false);
    if (!owner) return;
    const controller = new AbortController();
    void apiClient.getPredictionHistory({ symbol, limit: 1 }, controller.signal).then((data) => {
      if (!controller.signal.aborted) setHasPrediction(data.items.some((item) => item.prediction.symbol === symbol));
    }).catch(() => undefined);
    return () => controller.abort();
  }, [symbol, owner]);

  const visible = useMemo(() => {
    if (!rows.length) return [];
    const selected = selectChartRange(buildKlineSmartChartData(rows), range);
    return rows.slice(rows.length - selected.labels.length);
  }, [rows, range]);
  const ma20 = useMemo(() => movingAverage20(rows).slice(rows.length - visible.length), [rows, visible.length]);
  const earningsDates = ((dashboardData as unknown as { event_calendar?: Array<{ date?: string; type?: string }> })?.event_calendar ?? [])
    .filter((event) => event.type === 'earnings' && event.date).map((event) => event.date!);
  const chart = useMemo(() => buildContextChart(visible, { line, dark, convention, priceLevels, ma20, earningsDates }),
    [visible, line, dark, convention, priceLevels, ma20, earningsDates.join(',')]);
  const last = rows.at(-1);
  const previous = rows.at(-2);
  const currentPrice = quote.price ?? last?.close;
  const change = quote.change ?? (last && previous ? last.close - previous.close : undefined);
  const changePercent = quote.changePct ?? (change !== undefined && previous?.close ? change / previous.close * 100 : undefined);
  const company = companyProfile?.name_zh || companyProfile?.name || (asset?.display_name && asset.display_name !== symbol ? asset.display_name : '');
  const exchange = exchangeDisplayName(companyProfile?.exchange);
  const period = CHART_RANGES.find((item) => item.value === range)!.label.replace(' ', '');
  const valuation = dashboardData?.valuation;
  const metrics = [
    { label: '今开', value: number(last?.open), format: price },
    { label: '最高', value: number(last?.high), format: price },
    { label: '最低', value: number(last?.low), format: price },
    { label: '成交量', value: number(last?.volume), format: (value: number) => `${(value / 10000).toFixed(2)} 万` },
    { label: '市值', value: number(valuation?.market_cap) ?? number(companyProfile?.market_cap), format: largeNumber },
    { label: '市盈率', value: number(valuation?.trailing_pe) ?? number(companyProfile?.pe_ratio), format: (value: number) => `${value.toFixed(1)}x` },
    { label: `${period}最高`, value: visible.length ? Math.max(...visible.map((row) => row.high)) : undefined, format: price },
    { label: `${period}最低`, value: visible.length ? Math.min(...visible.map((row) => row.low)) : undefined, format: price },
    { label: '股息率', value: number(valuation?.dividend_yield) ?? number(companyProfile?.dividend_yield), format: (value: number) => `${(value * 100).toFixed(2)}%` },
  ];
  const shownMetrics = metrics.filter((metric) => metric.value !== undefined).length < 5 ? metrics.filter((metric) => metric.value !== undefined) : metrics;
  const date = asOf ? asOf.replace('T', ' ').replace(/\.\d+Z$/, 'Z').slice(0, 16) : '时间未注明';
  return <>
    <div>
      <div className={styles.company}>{company && <span className={styles.name}>{company}</span>}
        <span className={`num ${company ? styles.ticker : styles.name}`}>{symbol}{exchange ? ` · ${exchange}` : ''}</span></div>
      <div className={styles.priceRow}>
        <span className={`num ${styles.price}`}>{currentPrice !== undefined ? price(currentPrice) : '暂无报价'}</span>
        {change !== undefined && <span className={`num text-sm ${change > 0 ? 'text-t-up' : change < 0 ? 'text-t-down' : 'text-t-text3'}`}>
          {change > 0 ? '+' : ''}{change.toFixed(2)}{changePercent !== undefined ? ` (${changePercent > 0 ? '+' : ''}${changePercent.toFixed(2)}%)` : ''}</span>}
      </div>
      <p className={styles.time}>{date}{currency ? ` · ${currency}` : ''} · {dataKind === 'daily_close' ? '收盘价 · 非实时' : dataKind === 'intraday_snapshot' ? '盘中快照' : '行情时点未确认'} · {sourceDisplayName(source)}</p>
    </div>
    <div className={styles.controls}>
      <div className={styles.segments} role="group" aria-label="行情周期">{CHART_RANGES.map((item) => <button key={item.value} type="button"
        className={`${styles.segment} ${range === item.value ? styles.segmentActive : ''}`} aria-pressed={range === item.value}
        onClick={() => setRange(item.value)}>{item.label.replace(' ', '')}</button>)}</div>
      <div className={styles.segments} style={{ marginLeft: 'auto' }} role="group" aria-label="行情图类型">
        <button type="button" aria-pressed={!line} className={`${styles.segment} ${!line ? styles.segmentActive : ''}`} onClick={() => setLine(false)}>K线</button>
        <button type="button" aria-pressed={line} className={`${styles.segment} ${line ? styles.segmentActive : ''}`} onClick={() => setLine(true)}>折线</button>
      </div>
    </div>
    <figure className="m-0">
      {loading ? <div className={styles.skeleton} role="status" aria-label="正在加载行情" /> : chart ? <div className={styles.chart} data-testid="context-chart-surface">
        <EChart option={chart} style={{ height: 236 }} notMerge />
      </div> : <div className={styles.error}><p>{error || '暂无可绘制的真实行情。'}</p>
        <button type="button" className="inline-flex items-center gap-2 text-t-accent" onClick={() => setAttempt((value) => value + 1)}><RefreshCw size={14} />重试行情</button></div>}
      {!loading && chart && <figcaption className={styles.caption}>
        {ma20.some((value) => value !== null) && <span><i className={styles.line} />20 日均线</span>}
        {priceLevels.length > 0 && <span><i className={styles.levelLine} />对话中提到的价位</span>}
        {visible.some((row) => typeof row.volume === 'number') && <span>下方为成交量</span>}
      </figcaption>}
    </figure>
    {!loading && shownMetrics.length > 0 && <dl className={styles.metrics}>{shownMetrics.map((metric) => <div key={metric.label}>
      <dt>{metric.label}</dt><dd className="num" title={metric.value === undefined ? dashboardData?.valuation_fallback_reason || '该指标暂无可用数据。' : undefined}>
        {metric.value === undefined ? '—' : metric.format(metric.value)}</dd></div>)}</dl>}
    {hasPrediction && <Link to={`/track-record?ticker=${encodeURIComponent(symbol)}&scope=personal`} className="text-xs text-t-accent">这只股票的预测记录 →</Link>}
  </>;
}
