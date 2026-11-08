/** 数据供应商名称统一投影；不把内部适配器名当作对外来源。 */
const SOURCE_NAMES: Record<string, string> = {
  yfinance: 'Yahoo Finance', yahoo: 'Yahoo Finance', yahoo_finance: 'Yahoo Finance',
  yahoo_chart: 'Yahoo Finance', yahoo_quote: 'Yahoo Finance',
  akshare: 'AKShare', tushare: 'Tushare', finnhub: 'Finnhub',
  fmp: 'Financial Modeling Prep', financial_modeling_prep: 'Financial Modeling Prep',
  alpha_vantage: 'Alpha Vantage', alphavantage: 'Alpha Vantage',
  twelve_data: 'Twelve Data', twelvedata: 'Twelve Data',
  eastmoney: '东方财富', east_money: '东方财富', tencent: '腾讯财经',
  sina: '新浪财经', baostock: 'BaoStock', eodhd: 'EODHD',
  sec: '美国证券交易委员会', sec_edgar: '美国证券交易委员会',
  sec_company_facts: 'SEC Company Facts', fred: '美联储 FRED',
  sec_companyfacts: 'SEC Company Facts',
  reuters: '路透社', bloomberg: '彭博', company_ir: '公司投资者关系',
  market_chart: '来源未注明', unknown: '来源未注明', none: '来源未注明',
};

const INTERNAL_SOURCE_TITLES: Record<string, string> = {
  market_chart: '行情图表数据',
  get_stock_price: '股票行情数据',
  get_stock_historical_data: '历史行情数据',
  get_market_benchmark_history: '市场基准行情',
  get_company_info: '公司资料',
  get_company_news: '公司新闻',
  get_financial_statements: '财务报表',
  get_sec_company_facts_quarterly: 'SEC 季度财务数据',
  get_local_market_filings: '公司公告',
  get_earnings_estimates: '盈利预期数据',
  get_eps_revisions: '盈利预期修正',
  get_technical_snapshot: '技术指标数据',
  get_option_chain_metrics: '期权指标数据',
  get_relative_strength: '相对强弱数据',
  get_performance_comparison: '行情表现对比',
  get_fred_data: '宏观经济数据',
  get_official_macro_releases: '官方宏观公告',
  get_event_calendar: '事件日历',
  fetch_url_content: '网页资料',
  read_document: '文档资料',
  read_evidence: '研究证据',
  search_knowledge: '知识库资料',
  search: '搜索资料',
  analyze_dataset: '数据分析结果',
  run_analysis_code: '代码计算结果',
  run_python_compute: '指标计算结果',
};

const sourceKey = (value: string) => value.toLowerCase().replace(/[\s-]+/g, '_');
const sourceFamily = (name: string, key: string) => /^[a-z0-9_-]+$/i.test(name)
  ? Object.keys(SOURCE_NAMES).find((source) => key.startsWith(`${source}_`)) : undefined;

/** 只识别明确的数据服务/媒体名称，供缺少provider字段的来源标题兼容使用。 */
export function knownSourceDisplayName(value?: string | null): string | undefined {
  const name = value?.trim();
  if (!name) return undefined;
  const key = sourceKey(name);
  const family = sourceFamily(name, key);
  const mapped = SOURCE_NAMES[key] || (family ? SOURCE_NAMES[family] : undefined);
  return mapped && mapped !== '来源未注明' && mapped !== '其他数据来源' ? mapped : undefined;
}

export function sourceDisplayName(value?: string | null): string {
  const name = value?.trim();
  if (!name) return '来源未注明';
  const key = sourceKey(name);
  const family = sourceFamily(name, key);
  return SOURCE_NAMES[key] || INTERNAL_SOURCE_TITLES[key]
    || (family ? SOURCE_NAMES[family] : name.includes('_') ? '其他数据来源' : name);
}

/** ledger 标题只替换已知内部标识；正常文章标题（即使含下划线）保持原文。 */
export function sourceTitleDisplayName(title?: string | null, source?: string | null): string {
  const name = title?.trim();
  if (!name) return sourceDisplayName(source);
  if (/^dataset_[a-zA-Z0-9_-]+$/.test(name)) return '研究数据';
  const key = name.toLowerCase();
  const toolOutput = key.endsWith(' output') ? INTERNAL_SOURCE_TITLES[key.slice(0, -7)] : undefined;
  return INTERNAL_SOURCE_TITLES[key] || SOURCE_NAMES[key] || toolOutput || name;
}
