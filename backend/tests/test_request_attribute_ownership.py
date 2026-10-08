"""属性义务按结构语义归属，使用旧 SPY 真实抽取的最小回放。"""
import asyncio
from copy import deepcopy
from importlib import import_module

import pytest

from backend.graph.request_compiler import compile_semantic_contract
from backend.graph.semantic_requirements import SemanticConstraint


SPY_QUERY = "我想知道 SPY 最近五个已经结束的交易日累计涨跌多少，同时列出终点收盘价和美元单位；今天没开市就用最近收盘，说明你是否计入分红。"


def replay_semantics():
    scope = {'kind': 'trading_sessions', 'selection': 'latest_complete', 'count': 5, 'completed_only': True,
             'source_text': '最近五个已经结束的交易日', 'direction': 'past', 'unit': 'trading_days',
             'as_of': None, 'period_start': None, 'period_end': None}
    close_scope = {**scope, 'kind': 'latest_quote', 'count': None, 'unit': None}
    rows = [
        {'source_text': '我想知道 SPY 最近五个已经结束的交易日累计涨跌多少', 'metric': 'cumulative_return', 'measurement': 'return',
         'attributes': ['currency', 'dividends_included', 'price_basis'], 'time_scope': scope},
        {'source_text': '同时列出终点收盘价和美元单位', 'metric': 'quote', 'measurement': 'price', 'price_role': 'window_end',
         'attributes': ['currency', 'price_basis'], 'time_scope': {**close_scope, 'source_text': '终点收盘价'}},
        {'source_text': '今天没开市就用最近收盘', 'metric': 'quote', 'measurement': 'price', 'price_role': 'latest_completed_close',
         'attributes': ['currency', 'price_basis'], 'time_scope': {**close_scope, 'source_text': '最近收盘'}},
        {'source_text': '说明你是否计入分红', 'metric': 'unknown', 'measurement': 'other',
         'attributes': ['dividends_included'], 'time_scope': scope},
    ]
    for row in rows:
        row.update(description=row['source_text'], metric_text=row['source_text'], kind='fact_attribute',
                   subject='SPY', subject_refs=['SPY'], components=[], requires_analysis=False)
    return {'subjects': [{'id': 'SPY', 'type': 'index', 'label': 'SPY', 'tickers': ['SPY']}], 'requirements': rows}


def compiled(raw=None):
    return compile_semantic_contract({'query': SPY_QUERY}, raw or replay_semantics(), {})


def test_registered_attribute_preserves_original_id_and_gets_unique_metric_owner():
    rows = compiled()['understanding']['semantic_contract']['requirements']
    attribute = rows[-1]
    changed = replay_semantics()
    changed['requirements'][-1]['description'] = '模型改写的描述不改变原始要求身份'
    assert attribute['requirement_id'] == compiled(changed)['understanding']['semantic_contract']['requirements'][-1]['requirement_id']
    assert attribute['source_text'] == '说明你是否计入分红'
    assert attribute['metric'] == 'cumulative_return' and attribute['raw_metric'] == 'unknown'
    assert attribute['capability_status'] == 'supported'
    assert attribute['attribute_owner_requirement_id'] == rows[0]['requirement_id']
    assert attribute['evidence_kinds'] == ['price_window'] and not attribute['requires_analysis']


@pytest.mark.parametrize('change', ['unknown_attribute', 'numeric_component', 'different_scope', 'different_subject', 'qualitative_unknown', 'ambiguous_owner'])
def test_true_unknown_or_ambiguous_attribute_stays_unsupported(change):
    raw = replay_semantics()
    attribute = raw['requirements'][-1]
    if change == 'unknown_attribute': attribute['attributes'] = ['unregistered_property']
    if change == 'numeric_component': attribute['components'] = ['unknown_numeric_metric']
    if change == 'different_scope': attribute['time_scope'] = {**attribute['time_scope'], 'count': 20}
    if change == 'different_subject':
        raw['subjects'].append({'id': 'QQQ', 'type': 'index', 'label': 'QQQ', 'tickers': ['QQQ']})
        attribute.update(subject='QQQ', subject_refs=['QQQ'])
    if change == 'qualitative_unknown': attribute['measurement'] = 'qualitative'
    if change == 'ambiguous_owner':
        attribute['attributes'] = ['source_timestamp']
        owner = {**deepcopy(raw['requirements'][0]), 'metric': 'max_drawdown', 'source_text': '累计涨跌多少'}
        raw['requirements'].insert(1, owner)
    assert compiled(raw)['understanding']['semantic_contract']['requirements'][-1]['capability_status'] == 'unsupported'


def test_official_source_policy_is_flattened_without_replacing_original_constraint():
    query = '仅使用官方原始声明并附链接。'
    constraint = SemanticConstraint(constraint_type='source_policy', source_text='仅使用官方原始声明', source_requirement='primary').model_dump()
    raw = {'subjects': [{'id': 'doc', 'type': 'research_doc', 'label': '声明', 'tickers': []}], 'requirements': [
        {'kind': 'constraint', 'metric': 'unknown', 'source_text': '仅使用官方原始声明', 'description': '仅限原始声明',
         'subject_refs': ['doc'], 'constraints': [constraint]}], 'constraints': [constraint]}
    result = compile_semantic_contract({'query': query}, raw, {})
    row = result['understanding']['semantic_contract']['requirements'][0]
    assert row['constraint_type'] == 'source_policy' and row['source_requirement'] == 'primary'
    assert row['source_text'] == constraint['source_text']
    assert result['understanding']['semantic_contract']['constraints'][0] == constraint


def test_subject_scoped_exclusion_does_not_block_other_company_financials():
    query = 'TSLA 只看股价，不查基本面；AAPL 看经营现金流，仅按官方声明。'
    constraints = [
        {'constraint_type': 'exclude_dimension', 'dimension': 'fundamental_quality', 'source_text': '不查基本面', 'scope_refs': ['tsla']},
        {'constraint_type': 'source_policy', 'source_text': '仅按官方声明', 'source_requirement': 'primary', 'subject_refs': ['aapl']},
    ]
    raw = {'subjects': [{'id': 'tsla', 'type': 'company', 'label': 'TSLA', 'tickers': ['TSLA']}, {'id': 'aapl', 'type': 'company', 'label': 'AAPL', 'tickers': ['AAPL']}],
           'constraints': constraints, 'requirements': [
        {'source_text': 'TSLA 只看股价', 'description': '价格', 'kind': 'fact_attribute', 'metric': 'quote', 'subject': 'TSLA', 'subject_refs': ['tsla']},
        {'source_text': 'AAPL 看经营现金流', 'description': '现金流', 'kind': 'fact_attribute', 'metric': 'operating_cash_flow', 'subject': 'AAPL', 'subject_refs': ['aapl']},
        {'source_text': '不查基本面', 'description': '不查基本面', 'kind': 'constraint', 'metric': 'unknown'},
    ]}
    result = compile_semantic_contract({'query': query}, raw, {})
    tasks = {task['tickers'][0]: task for task in result['tasks']}
    assert [item['constraint_type'] for item in tasks['TSLA']['constraints']] == ['exclude_dimension']
    assert [item['source_requirement'] for item in tasks['AAPL']['constraints']] == ['primary']
    assert all(not any(item['constraint_type'] == 'exclude_dimension' for item in row['constraints']) for row in tasks['AAPL']['answer_requirements'])
    exclusion = next(row for row in tasks['TSLA']['answer_requirements'] if row['kind'] == 'constraint')
    assert exclusion['subject_refs'] == ['tsla']
    frames = {frame['subject']['tickers'][0]: frame for frame in result['request_frames']}
    assert frames['TSLA']['excluded_facets'] == ['fundamental_quality'] and frames['AAPL']['excluded_facets'] == []
    assert SemanticConstraint.model_validate(constraints[0]).subject_refs == ['tsla']


def test_unbound_constraint_scope_fails_closed():
    raw = replay_semantics()
    raw['constraints'] = [{'constraint_type': 'source_policy', 'source_text': '说明你是否计入分红', 'source_requirement': 'primary', 'subject_refs': ['invented_subject']}]
    with pytest.raises(ValueError, match='request_constraint_subject_unbound'):
        compiled(raw)


def test_frozen_spy_model_replay_answers_attribute_through_complete_graph(monkeypatch):
    from backend.graph.runner import GraphRunner
    routing = import_module('backend.graph.nodes.route_request')
    tools = import_module('backend.langchain_tools')
    synthesis = import_module('backend.graph.synthesis.research_synthesis')
    calls = []
    async def extract(state, seed):
        return replay_semantics(), {'status': 'confirmed', 'source': 'frozen_spy_v3_replay'}
    def window(ticker, sessions, metrics, as_of, price_basis):
        calls.append(metrics)
        dates = ['2026-09-25', '2026-09-28', '2026-09-29', '2026-09-30', '2026-10-01', '2026-10-02']
        closes = [771.3499755859375, 765.6099853515625, 764.2000122070312, 762.6300048828125, 763.989990234375, 769.6400146484375]
        payload = {'ticker': ticker, 'subject': ticker, 'kind': 'price_window', 'sessions': sessions, 'completed_only': True,
            'metrics': {'cumulative_return': {'value': closes[-1] / closes[0] - 1, 'base_close': closes[0], 'end_close': closes[-1],
                'base_date': dates[0], 'end_date': dates[-1], 'intervals': sessions}},
            'bars': [{'date': day, 'close': close} for day, close in zip(dates, closes)], 'currency': 'USD', 'unit': 'USD',
            'price_basis': 'split_adjusted_close', 'dividends_included': False, 'source_timestamp': dates[-1], 'as_of': dates[-1],
            'period_start': dates[0], 'period_end': dates[-1], 'end_close': closes[-1], 'source': 'yfinance',
            'source_url': 'https://finance.yahoo.com/quote/SPY/history/', 'error': None, 'missing_metrics': [], 'observation_count': sessions,
            'missing_session_dates': [], 'expected_session_dates': dates, 'market_session': 'regular_close'}
        payload['structured_data'] = dict(payload)
        return payload
    async def forbidden(**kwargs):
        pytest.fail('纯计算与属性回放不得调用研究模型')
    monkeypatch.setattr(routing, 'extract_semantic_requirements', extract)
    monkeypatch.setattr(tools, '_get_price_window_metrics', window)
    monkeypatch.setattr(synthesis, '_invoke_structured', forbidden)
    monkeypatch.setenv('LANGGRAPH_EXECUTE_LIVE_TOOLS', 'true')
    monkeypatch.setenv('JINA_ENRICH_EVIDENCE', 'false')
    state = asyncio.run(GraphRunner.create().ainvoke(thread_id='spy-attribute-owner-replay', query=SPY_QUERY, output_mode='chat'))
    assert calls == [['cumulative_return']]
    assert state['trace']['analysis']['role'] == 'deterministic_renderer'
    quality = state['artifacts']['result_quality']
    assert quality['answer_status'] == 'answered' and quality['state'] == 'pass'
