import { describe, expect, it } from 'vitest';
import { sourceDisplayName, sourceTitleDisplayName } from './sourceDisplayName';

describe('source display names', () => {
  it('uses supplier names instead of adapter identifiers and preserves an unknown named source', () => {
    expect(sourceDisplayName('yfinance')).toBe('Yahoo Finance');
    expect(sourceDisplayName('eastmoney')).toBe('东方财富');
    expect(sourceDisplayName('Reuters')).toBe('路透社');
    expect(sourceDisplayName('香港交易所')).toBe('香港交易所');
    expect(sourceDisplayName('market_chart')).toBe('来源未注明');
    expect(sourceDisplayName('yfinance_quote_fallback')).toBe('Yahoo Finance');
    expect(sourceDisplayName('custom_provider_adapter')).toBe('其他数据来源');
    expect(sourceDisplayName()).toBe('来源未注明');
  });
  it('maps only known internal ledger titles while preserving real article titles', () => {
    expect(sourceTitleDisplayName('twelve_data')).toBe('Twelve Data');
    expect(sourceTitleDisplayName('get_stock_historical_data')).toBe('历史行情数据');
    expect(sourceTitleDisplayName('get_stock_historical_data output')).toBe('历史行情数据');
    expect(sourceTitleDisplayName('analyze_dataset output')).toBe('数据分析结果');
    expect(sourceTitleDisplayName('market_chart')).toBe('行情图表数据');
    expect(sourceTitleDisplayName('AAPL_2026_Q4：公司业绩公告')).toBe('AAPL_2026_Q4：公司业绩公告');
    expect(sourceTitleDisplayName('yfinance_2026_research_article')).toBe('yfinance_2026_research_article');
    expect(sourceTitleDisplayName('Market Chart')).toBe('Market Chart');
    expect(sourceTitleDisplayName('get_stock_historical_data output 的使用说明')).toBe('get_stock_historical_data output 的使用说明');
    expect(sourceTitleDisplayName('', 'twelve_data')).toBe('Twelve Data');
  });
});
