"""保留首次验收发现的边界：测用户请求到执行计划，不只镜像正则。"""
import asyncio

import pytest

from backend.config.ticker_mapping import extract_tickers, normalize_ticker
from backend.graph.nodes.prepare_context import prepare_context
from backend.graph.nodes.route_request import route_request
from backend.graph.nodes.policy_gate import policy_gate
from backend.graph.planning.rule_planner import rule_based_planner
from backend.graph.request_constraints import parse_time_scope


def compile_request(query, *, history=None, mode='chat'):
    state = {'query':query,'thread_id':'compiler-fixture','output_mode':mode,'ui_context':{'session_history':history or []}}
    state.update(prepare_context(state))
    state.update(asyncio.run(route_request(state)))
    if state['understanding']['route']=='research':
        state.update(policy_gate(state))
        state.update(rule_based_planner(state))
    return state


@pytest.mark.parametrize('query,tickers', [
    ('Visa（V）和 Mastercard（MA）的现金流比较', ['V','MA']),
    ('COST 看经营基本面', ['COST']),
    ('阿里巴巴港股 9988.HK 最新财务', ['9988.HK']),
    ('研究阿里巴巴港股', ['9988.HK']),
    ('比较 BABA 和 9988.HK 的流动性', ['BABA','9988.HK']),
    ('BTC-USD 与 Bitcoin 是同一个标的吗', ['BTC-USD']),
    ('Explain cost of capital with a fictional example', []),
])
def test_entities_preserve_explicit_listing_and_finance_words(query,tickers):
    assert extract_tickers(query)['tickers']==tickers
    assert normalize_ticker('Bitcoin')=='BTC-USD'


def test_negative_dimensions_do_not_spawn_excluded_tools():
    state=compile_request('只看 AVGO 的技术面：日线趋势、RSI、MACD、支撑和阻力，不需要新闻或基本面。')
    tools={step['name'] for step in state['plan_ir']['steps']}
    assert {'get_technical_snapshot','get_stock_price'} <= tools
    assert not tools.intersection({'get_company_news','news_agent','fundamental_agent','get_sec_filings'})
    assert state['intent_contract']['facets']==['trend','technical']


def test_mixed_subjects_keep_their_own_task_query_and_asset_type():
    state=compile_request('XOM 看近期新闻，COST 看经营基本面，BTC-USD 看价格趋势；请分别回答，不要把三种任务混在一起。')
    tasks={task['tickers'][0]:task for task in state['tasks']}
    assert set(tasks)=={'XOM','COST','BTC-USD'}
    assert tasks['BTC-USD']['subject_type']=='crypto'
    assert tasks['COST']['operation']['params']['facets']==['fundamental']
    btc_steps=[step for step in state['plan_ir']['steps'] if 'BTC-USD' in step.get('subject_tickers',[])]
    assert {'get_sec_filings','get_company_info','get_option_chain_metrics'}.isdisjoint(s['name'] for s in btc_steps)
    for step in state['plan_ir']['steps']:
        if step['name']=='get_authoritative_media_news':
            assert 'COST' not in step['inputs']['query'] and 'BTC-USD' not in step['inputs']['query']


@pytest.mark.parametrize('query,field,value', [('未来90天有哪些事件','days_ahead',90),('最近72小时的新闻','hours_back',72),('next 2 weeks','days_ahead',14),('past 48 hours','hours_back',48),('未来三个月催化','days_ahead',90)])
def test_explicit_time_windows_survive_normalization(query,field,value):
    assert parse_time_scope(query)[field]==value


def test_news_window_reaches_actual_tool_arguments():
    state=compile_request('汇总 NFLX 最近72小时的新闻，合并同一事件的重复报道。')
    news=[s for s in state['plan_ir']['steps'] if s['name'] in {'get_company_news','get_authoritative_media_news'}]
    assert len(news)==2
    assert all(s['inputs']['max_age_hours']==72 for s in news)
    assert any(r['kind']=='event_window' for r in state['tasks'][0]['answer_requirements'])


def test_history_subject_and_forward_window_are_inherited_together():
    state=compile_request('沿用刚才这家公司，未来90天哪些已确认事件值得跟踪？',history=[{'role':'user','content':'ORCL 最新财报表现'},{'role':'assistant','content':'ORCL 已披露季度财报。'}])
    assert state['subject']['tickers']==['ORCL']
    calendar=next(s for s in state['plan_ir']['steps'] if s['name']=='get_event_calendar')
    assert calendar['inputs']=={'ticker':'ORCL','days_ahead':90}


def test_history_citations_and_previous_topics_do_not_expand_current_subject():
    state=compile_request('沿用刚才这家公司，未来90天哪些事件值得跟踪？',history=[
        {'role':'user','content':'AAPL 最新财报'}, {'role':'assistant','content':'AAPL 的季度信息。'},
        {'role':'user','content':'甲骨文 ORCL 最近财报如何？'},
        {'role':'assistant','content':'Oracle (NYSE:ORCL) reported earnings. Its drawdown is elevated. Peers include MSFT.\n## 来源\nNASDAQ:NVDA article https://example.com/downside'},
    ])
    assert state['subject']['tickers']==['ORCL']
    assert extract_tickers('Oracle (NYSE:ORCL) drawdown')['tickers']==['ORCL']
    assert extract_tickers('Nasdaq index trend')['tickers']==['^IXIC']


def test_missing_subject_clarifies_without_research():
    state=compile_request('现在还值得买它吗？')
    assert state['understanding']['route']=='clarify'
    assert '请补充' in state['artifacts']['draft_markdown']
    assert not (state.get('plan_ir') or {}).get('steps')


@pytest.mark.parametrize('mode', ['chat', 'brief', 'investment_report'])
def test_missing_subject_question_survives_full_graph(mode, monkeypatch):
    from backend.graph.runner import GraphRunner, _build_graph

    # 复现旧 h10：route 正确，最终 renderer 却将澄清问题替换成证据不足。
    monkeypatch.setenv('FINSIGHT_FINANCIAL_TERM_RESOLVER', 'off')
    state = asyncio.run(GraphRunner(_graph=_build_graph(checkpointer=None)).ainvoke(
        thread_id='missing-subject-full-graph', query='现在还值得买它吗？',
        output_mode=mode,
    ))
    assert state['understanding']['route'] == 'clarify'
    assert state['artifacts']['draft_markdown'] == state['clarify']['question']
    assert '请补充' in state['artifacts']['draft_markdown']
    assert state['messages'][-1].content == state['clarify']['question']
    assert state['trace']['analysis']['status'] == 'skipped'
    assert not state['artifacts'].get('step_results')


def test_concept_question_requests_direct_explanation_without_market_tools():
    state=compile_request('自由现金流和净利润为什么会差很多？用虚构数字举例即可，不要查询股票行情。')
    assert state['understanding']['route']=='direct'
    assert state['artifacts']['direct_answer_request']['query']==state['query']
    assert not (state.get('plan_ir') or {}).get('steps')


def test_implicit_asset_followup_is_not_reclassified_as_a_concept():
    state=compile_request('为什么会跌？',history=[{'role':'user','content':'分析 ORCL 最近走势'},{'role':'assistant','content':'ORCL 的价格下跌。'}])
    assert state['understanding']['route']=='research'
    assert state['subject']['tickers']==['ORCL']
    assert 'direct_answer_request' not in state['artifacts']


def test_report_requests_actual_disclosure_text_and_all_six_dimensions():
    state=compile_request('给我一份 Salesforce（CRM）的正式投资研究报告，覆盖业务、竞争、最新财务、估值、未来90天催化和风险，关键事实附可追溯来源。',mode='investment_report')
    assert len(state['request_frame']['render_contract']['dimensions'])==6
    filings=[s for s in state['plan_ir']['steps'] if s['name']=='get_sec_filings']
    assert any(s['inputs'].get('include_content') for s in filings)
    assert next(s for s in state['plan_ir']['steps'] if s['name']=='get_event_calendar')['inputs']['days_ahead']==90


def test_hong_kong_research_plans_quote_and_profile_without_us_sec():
    state=compile_request('研究阿里巴巴港股 9988.HK 最新财务、估值和风险，只分析这个上市代码。')
    names={s['name'] for s in state['plan_ir']['steps']}
    assert state['subject']['tickers']==['9988.HK']
    assert {'get_stock_price','get_company_info','get_local_market_filings'} <= names
    assert 'get_sec_company_facts_quarterly' not in names


def test_comparison_support_tasks_prepare_facts_without_duplicate_analysis():
    from backend.graph.synthesis.analysis_requirements import analysis_task_modes
    state=compile_request('Visa（V）和 Mastercard（MA）谁的估值更贵、自由现金流质量更好？用可比较财期，并解释差异。')
    parent=next(t for t in state['tasks'] if t['operation']['name']=='compare')
    supports=[t for t in state['tasks'] if t.get('evidence_support_for')==parent['id']]
    assert {t['tickers'][0] for t in supports}=={'V','MA'}
    assert all(not r['requires_analysis'] for t in supports for r in t['answer_requirements'])
    modes=analysis_task_modes(state)
    assert modes[parent['id']]=='research'
    assert all(modes[t['id']]=='deterministic' for t in supports)


def test_conditional_macro_chain_preserves_cause_and_each_requested_effect():
    query='如果最近原油价格走高，会怎样传导到美国通胀、利率预期与航空股？区分已发生的数据和假设推演。'
    state=compile_request(query)
    assert len(state['tasks'])==1
    task=state['tasks'][0]
    assert task['request_text']==query
    requirements={r['requirement_id'].split(':')[-1]:r for r in task['answer_requirements']}
    assert {'inflation','rates','sector','price_context'} <= set(requirements)
    assert all(requirements[key]['requires_explicit_binding'] for key in ('inflation','rates','sector'))
    assert state['trace']['coverage_validator']['status']=='ok'
