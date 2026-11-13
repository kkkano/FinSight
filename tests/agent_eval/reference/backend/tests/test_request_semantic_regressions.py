"""冻结旧题的最小语义回放，不依赖网络或付费模型。"""
from copy import deepcopy

import pytest

from backend.graph.request_compiler import compile_semantic_contract


def _compile(query, ticker, rows, constraints=None):
    for row in rows:
        row.setdefault('description', row['source_text'])
        row.setdefault('subject', ticker)
        row.setdefault('subject_refs', [ticker])
    return compile_semantic_contract({'query': query}, {'subjects': [{'id': ticker, 'type': 'company', 'label': ticker, 'tickers': [ticker]}],
                                    'requirements': rows, 'constraints': constraints or []}, {})


def test_frozen_msft_quantity_distinction_gets_analysis_without_promoting_to_numeric_metric():
    query = '上一个已披露完整财年减少了多少流通股？区分回购金额与净股数变化，先不要谈未来股价。'
    fiscal = {'kind': 'fiscal_year', 'selection': 'latest_complete', 'count': None, 'completed_only': True, 'source_text': '上一个已披露完整财年'}
    result = _compile(query, 'MSFT', [
        {'source_text': '减少了多少流通股', 'kind': 'fact_attribute', 'metric': 'net_share_change', 'time_scope': fiscal, 'requires_analysis': False},
        {'source_text': '区分回购金额与净股数变化', 'kind': 'constraint', 'metric': 'unknown', 'time_scope': fiscal, 'requires_analysis': False},
        {'source_text': '先不要谈未来股价', 'kind': 'constraint', 'metric': 'unknown', 'time_scope': fiscal, 'requires_analysis': False},
    ], [{'constraint_type': 'exclude_dimension', 'dimension': 'future_price', 'source_text': '先不要谈未来股价', 'subject_refs': ['MSFT']}])
    rows = result['tasks'][0]['answer_requirements']
    assert not rows[0]['requires_analysis']
    assert rows[1]['requires_analysis'] and rows[1]['metric'] == 'unknown' and rows[1]['evidence_kinds'] == []
    assert not rows[2]['requires_analysis'] and rows[2]['constraint_type'] == 'exclude_dimension'


def test_frozen_adbe_quote_normalizes_only_registered_identifiers_and_keeps_snapshot_price_field():
    query = 'ADBE 最近一次可用报价是多少？告诉我币种、报价时间和是否为盘后价格，别把它说成实时价。'
    scope = {'kind': 'latest_quote', 'selection': 'latest_complete', 'count': None, 'completed_only': True, 'source_text': '最近一次可用报价'}
    raw = [{'source_text': 'ADBE 最近一次可用报价是多少？告诉我币种、报价时间和是否为盘后价格', 'kind': 'fact_attribute', 'metric': 'quote',
            'price_role': 'latest_completed_close', 'time_scope': scope, 'attributes': [':currency', ':source_timestamp', ':market_session', ':not_registered']},
           {'source_text': '别把它说成实时价', 'kind': 'constraint', 'metric': 'unknown', 'time_scope': scope}]
    result = _compile(query, 'ADBE', deepcopy(raw))
    rows = result['tasks'][0]['answer_requirements']
    assert set(rows[0]['attributes']) == {'currency', 'source_timestamp', 'market_session'}
    assert rows[0]['unmapped_qualifiers'] == [{'name': ':not_registered', 'source_text': raw[0]['source_text']}]
    assert rows[0]['capability_status'] == 'supported'
    assert 'end_close' not in rows[0]['attributes']
    assert all(not row['requires_analysis'] for row in rows)
    assert result['trace']['request_requirements']['raw_semantic']['requirements'][0]['attributes'][0] == ':currency'


@pytest.mark.parametrize('metric', ['rsi', 'rsi14', 'macd', 'support', 'resistance', 'support_resistance', 'trend_quality'])
def test_existing_daily_technical_measurement_does_not_need_user_supplied_trading_window(metric):
    query = '只看 AVGO 的日线指标，不需要新闻或基本面。'
    result = _compile(query, 'AVGO', [{'source_text': '日线指标', 'kind': 'fact_attribute', 'metric': metric,
         'time_scope': {'kind': 'trading_sessions', 'count': None, 'selection': 'latest_complete', 'completed_only': True, 'source_text': '日线指标', 'unit': 'trading_day'},
         'attributes': ['timeframe:daily'], 'requires_analysis': True}])
    row = result['tasks'][0]['answer_requirements'][0]
    assert row['capability_status'] == 'supported'
    assert row['data_frequency'] == 'daily' and row['time_scope']['kind'] == 'none'
    assert row['metric'] == ('rsi14' if metric == 'rsi' else metric)
    assert row['attributes'] == [] and 'technical_snapshot' in row['evidence_kinds']
    if metric != 'trend_quality':
        assert not row['requires_analysis']


@pytest.mark.parametrize('metric', ['fundamental_quality', 'valuation_reasonableness', 'risk_level', 'business_model', 'competition', 'macro_impact', 'earnings_impact', 'investment_attractiveness'])
def test_known_qualitative_metric_cannot_be_downgraded_by_model_fact_flag(metric):
    query = '研究 9988.HK 最新财务、估值和风险。'
    result = _compile(query, '9988.HK', [{'source_text': '最新财务、估值和风险', 'kind': 'fact_attribute', 'metric': metric, 'requires_analysis': False}])
    assert result['tasks'][0]['answer_requirements'][0]['requires_analysis']
