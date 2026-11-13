/** 工具协议标识的统一中文展示；未知标识保留在诊断详情。 */
export const TOOL_ACTIVITY_LABELS: Record<string, string> = {
  get_stock_price: '获取行情', get_company_news: '读取公司新闻', search: '搜索资料',
  fetch_url_content: '读取网页', get_stock_historical_data: '获取历史行情',
  get_sec_company_facts_quarterly: '读取季度财报', get_local_market_filings: '读取公司公告',
  search_knowledge: '检索历史资料', read_document: '读取文档', search_memory: '检索研究记录',
  run_analysis_code: '分析数据', run_python_compute: '计算指标', render_chart: '绘制图表',
  delegate_research: '分工研究', send_agent_message: '补充问题', await_agent_results: '汇总结果',
  discover_tools: '查找工具', enable_tools: '启用工具', read_evidence: '读取资料',
  read_selection: '读取选中资料', get_earnings_estimates: '获取盈利预期', get_eps_revisions: '获取盈利预期修正',
  get_company_info: '获取公司信息', get_financial_statements: '读取财务报表', get_current_datetime: '查看时间',
  get_technical_snapshot: '计算技术指标', get_market_benchmark_history: '获取基准行情',
  get_relative_strength: '计算相对强弱', analyze_historical_drawdowns: '分析历史回撤',
  get_performance_comparison: '比较价格表现', get_option_chain_metrics: '读取期权指标',
  get_news_sentiment: '分析新闻情绪', get_event_calendar: '读取事件日历',
  score_news_source_reliability: '核查新闻来源', get_market_sentiment: '读取市场情绪',
  get_fred_data: '读取宏观数据', get_official_macro_releases: '读取官方宏观公告',
  get_economic_events: '读取经济事件', get_factor_exposure: '计算风险因子敞口',
  analyze_dataset: '分析数据', get_watchlist: '读取自选清单',
  mark_report: '整理研究报告', propose_action: '提出待确认操作',
  discover_skills: '查找技能', use_skill: '应用技能',
};

export const researchToolLabel = (name: string): string => TOOL_ACTIVITY_LABELS[name] || '整理资料';
