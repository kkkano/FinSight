import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { hasDataSourceDetails, publicSourceText, SourceDetails, sourceDetailRows } from './SourceDetails';

describe('数据来源详情', () => {
  it('没有原文链接时仍提供可展开的来源入口', () => {
    const html = renderToStaticMarkup(<SourceDetails source={{ title: 'get_technical_snapshot output', source_name: 'yfinance' }} index={2} />);
    expect(html).toContain('aria-label="查看来源 3 详情"');
    expect(html).toContain('aria-expanded="false"');
    expect(html).toContain('技术指标数据');
    expect(html).not.toContain('get_technical_snapshot');
  });

  it('显示真实供应商、行情口径和参数，不暴露内部编号和未知元数据', () => {
    const rows = sourceDetailRows({ source: 'get_technical_snapshot', source_name: 'yfinance', as_of: '2026-11-06',
      currency: 'USD', price_basis: 'split_adjusted_close', dividends_included: false,
      meta: { market_session: 'regular_close', parameters: { rsi_period: 14, ma_periods: [20, 50, 200] },
        data_ref: 'dataset_private123', endpoint_url: 'https://private.example' } });
    expect(rows).toContainEqual({ label: '数据来源', value: 'Yahoo Finance' });
    expect(rows).toContainEqual({ label: '价格口径', value: '拆股调整收盘价' });
    expect(rows).toContainEqual({ label: '计入股息', value: '否' });
    expect(rows).toContainEqual({ label: 'RSI 周期', value: '14' });
    expect(rows).toContainEqual({ label: '均线周期', value: '20、50、200' });
    expect(JSON.stringify(rows)).not.toMatch(/private|dataset_|get_technical/);
  });

  it('未提供日期时不制造时间，并将遗留的资料编号换成白话', () => {
    expect(sourceDetailRows({ source: 'sec_companyfacts' })).toEqual([{ label: '数据来源', value: 'SEC Company Facts' }]);
    expect(publicSourceText('根据 dataset_abc123 的计算结果')).toBe('根据 研究数据 的计算结果');
  });

  it('有原文地址的数据来源仍保留口径详情，新闻直接打开原文', () => {
    expect(hasDataSourceDetails({ kind: 'technical_snapshot', url: 'https://example.com/history' })).toBe(true);
    expect(hasDataSourceDetails({ currency: 'USD', url: 'https://example.com/filing' })).toBe(true);
    expect(hasDataSourceDetails({ kind: 'news_context', metadata: { description: '公司公告新闻' } })).toBe(false);
  });
});
