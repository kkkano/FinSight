import { useEffect, useState } from 'react';
import { ChevronDown, ChevronRight, ExternalLink } from 'lucide-react';
import type { EvidenceItem } from '../../types';
import { knownSourceDisplayName, sourceDisplayName, sourceTitleDisplayName } from '../../utils/sourceDisplayName';

const FIELD_LABELS: Record<string, string> = {
  as_of: '数据截至', published_date: '发布时间', observed_at: '获取时间', currency: '货币', unit: '单位', period: '观察区间', ticker: '研究标的',
  price_basis: '价格口径', dividends_included: '计入股息', frequency: '数据频率', interval: '数据周期',
  market_session: '行情时段', source_time_precision: '时间精度', definition: '计算口径', description: '方法说明',
  rsi_period: 'RSI 周期', ma_periods: '均线周期', macd_fast: 'MACD 快线', macd_slow: 'MACD 慢线',
  macd_signal: 'MACD 信号线', bollinger_period: '布林带周期', bollinger_std: '布林带标准差',
  operation: '计算方法', window: '统计窗口',
};
const VALUE_LABELS: Record<string, string> = {
  unknown: '未注明', regular_close: '常规收盘', regular: '常规交易', premarket: '盘前', postmarket: '盘后',
  date: '日期', datetime: '日期和时间', split_adjusted_close: '拆股调整收盘价', unadjusted_close: '未复权收盘价',
  total_return: '总回报', weekly: '周线', daily: '日线', monthly: '月线', quarterly: '季度', '1wk': '周线', '1d': '日线',
  max: '全部可用历史', series_statistics: '序列统计', consecutive_decline_streaks: '连续下跌区间统计',
  price_return_comparison: '区间价格涨跌幅对比', indexed_comparison: '价格走势对比', moving_average: '移动平均',
};

export const publicSourceText = (text: string) => text.replace(/\bdataset_[a-zA-Z0-9_-]+\b/g, '研究数据');

export function hasDataSourceDetails(source: EvidenceItem) {
  if (/news/.test(source.kind || '')) return false;
  const tool = String(source.metadata?.tool || source.meta?.tool || '');
  return Boolean(source.currency || source.unit || source.price_basis || source.dividends_included !== undefined
    || /^(?:get_stock_(?:price|historical_data)|get_technical_snapshot|analyze_dataset|run_analysis_code)$/.test(tool)
    || /(?:price|technical|filing|company_profile)/.test(source.kind || '')
    || Object.keys({ ...source.metadata, ...source.meta }).some((key) => key in FIELD_LABELS || key === 'parameters'));
}

export function sourceDetailRows(source: EvidenceItem) {
  const metadata = { ...source.metadata, ...source.meta };
  const parameters = metadata.parameters && typeof metadata.parameters === 'object' ? metadata.parameters : {};
  const method = metadata.method && typeof metadata.method === 'object' ? metadata.method : {};
  const fields = { ...method, ...metadata, ...parameters, ...source } as Record<string, unknown>;
  const rows = [{ label: '数据来源', value: knownSourceDisplayName(source.source_name) || knownSourceDisplayName(source.source)
    || sourceDisplayName(source.source_name || source.source) }];
  for (const [key, label] of Object.entries(FIELD_LABELS)) {
    const value = fields[key];
    if (value === null || value === undefined || value === '') continue;
    const text = typeof value === 'boolean' ? value ? '是' : '否'
      : Array.isArray(value) && value.every((item) => typeof item === 'number') ? value.join('、')
        : typeof value === 'string' || typeof value === 'number' ? String(value) : '';
    if (text) rows.push({ label, value: publicSourceText(VALUE_LABELS[text] || text) });
  }
  return rows;
}

/** 无文章地址的数据来源也能展开查看已保存的出处、时点和计算口径。 */
export function SourceDetails({ source, index, className, focused = false }: {
  source: EvidenceItem; index: number; className?: string; focused?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  useEffect(() => { if (focused) setExpanded(true); }, [focused]);
  const title = sourceTitleDisplayName(source.title, source.source_name || source.source);
  const snippet = source.snippet?.trim();
  const prose = snippet && !/^[{[]/.test(snippet) ? publicSourceText(snippet) : null;
  return <div>
    <button type="button" className={`${className || ''} w-full text-left`} aria-label={`查看来源 ${index + 1} 详情`}
      aria-expanded={expanded} onClick={() => setExpanded((value) => !value)}>
      <span className="num text-t-accent">{index + 1}</span><span>{title}</span>
      {expanded ? <ChevronDown size={13} className="ml-auto shrink-0" /> : <ChevronRight size={13} className="ml-auto shrink-0" />}
    </button>
    {expanded && <div className="my-1 rounded-lg border border-t-border bg-t-bg p-3 text-xs leading-6 text-t-text2" data-testid="source-details">
      <dl>{sourceDetailRows(source).map((row) => <div className="flex gap-3" key={row.label}>
        <dt className="shrink-0 text-t-text3">{row.label}</dt><dd className="min-w-0 break-words">{row.value}</dd>
      </div>)}</dl>
      {prose && <p className="mt-2 whitespace-pre-wrap break-words">{prose}</p>}
      {source.limitations?.map((limitation, position) => <p className="mt-1 break-words text-t-text3" key={position}>{publicSourceText(limitation)}</p>)}
      {source.url ? <a href={source.url} target="_blank" rel="noopener noreferrer" className="mt-2 inline-flex items-center gap-1 text-t-accent">
        打开原始资料 <ExternalLink size={12} />
      </a> : <p className="mt-2 text-t-text3">这份数据没有单独的原文链接。</p>}
    </div>}
  </div>;
}
