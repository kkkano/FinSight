"""宏观 selector 来源为确认后的规范要求，不再用原句挑默认指标。"""
import asyncio
from copy import deepcopy
from importlib import import_module

import pytest

from backend.graph.nodes.policy_gate import policy_gate
from backend.graph.planning.rule_planner import rule_based_planner
from backend.graph.request_compiler import compile_semantic_contract


QUERY = '核对最新报告数据，并解释主要影响。'


def semantics(*, composite=False, analysis=False):
    metrics = ['macro_data'] if composite else ['nonfarm_payroll_change', 'unemployment']
    rows = [{'source_text': '报告数据', 'description': metric, 'kind': 'fact_attribute', 'metric': metric,
             'subject_refs': ['macro_us'], 'requires_analysis': True,
             'components': ['nonfarm_payroll_change', 'unemployment'] if composite else []} for metric in metrics]
    if analysis:
        rows.append({'source_text': '解释主要影响', 'description': '因果传导', 'kind': 'explanation', 'metric': 'macro_impact',
                     'subject_refs': ['macro_us'], 'components': ['nonfarm_payroll_change', 'unemployment']})
    return {'subjects': [{'id': 'macro_us', 'type': 'macro', 'label': '美国宏观', 'tickers': []}], 'requirements': rows}


@pytest.mark.parametrize('composite', [False, True])
def test_primitive_and_composite_requirements_plan_exact_employment_selector(composite):
    state = {'query': QUERY, 'output_mode': 'chat', **compile_semantic_contract({'query': QUERY}, semantics(composite=composite), {})}
    state.update(policy_gate(state))
    result = rule_based_planner(state)
    assert result['trace']['planner']['validated']
    steps = result['plan_ir']['steps']
    fred = next(step for step in steps if step['name'] == 'get_fred_data')
    assert fred['inputs'] == {'indicators': ['nonfarm_payroll_change', 'unemployment'], 'as_of': None}
    official = next(step for step in steps if step['name'] == 'get_official_macro_releases')
    assert official['inputs']['include_content'] is True
    assert official['inputs']['query'].endswith(' employment situation')
    assert not any(step['name'] == 'macro_agent' for step in steps)


def test_explanation_agent_receives_same_structured_selector():
    state = {'query': QUERY, 'output_mode': 'chat', **compile_semantic_contract({'query': QUERY}, semantics(analysis=True), {})}
    state.update(policy_gate(state))
    result = rule_based_planner(state)
    agent = next(step for step in result['plan_ir']['steps'] if step['name'] == 'macro_agent')
    assert agent['inputs']['indicators'] == ['nonfarm_payroll_change', 'unemployment']
    assert agent['inputs']['as_of'] is None
    assert agent['data_dependencies']


def test_employment_selector_reaches_tool_registry_through_entire_graph(monkeypatch):
    from backend.graph.runner import GraphRunner
    routing = import_module('backend.graph.nodes.route_request')
    tools = import_module('backend.langchain_tools')
    synthesis = import_module('backend.graph.synthesis.research_synthesis')
    calls = []
    async def extract(state, seed):
        return deepcopy(semantics(composite=True)), {'status': 'confirmed'}
    def fred(**kwargs):
        calls.append(kwargs)
        return {'source': 'FRED', 'nonfarm_payroll_change': 29000, 'unemployment': 4.2,
                'indicator_metadata': {'nonfarm_payroll_change': {'unit': 'persons', 'report_month': '2026-09'},
                                       'unemployment': {'unit': 'percent', 'report_month': '2026-09'}}}
    def official(**kwargs):
        assert kwargs['include_content'] is True
        return {'releases': [], 'source': 'fixture', 'query': kwargs['query']}
    async def forbidden(**kwargs):
        pytest.fail('就业数值事实不应进入研究模型')
    monkeypatch.setattr(routing, 'extract_semantic_requirements', extract)
    monkeypatch.setattr(tools, '_get_fred_data', fred)
    monkeypatch.setattr(tools, '_get_official_macro_releases', official)
    monkeypatch.setattr(tools, '_get_authoritative_media_news', lambda **kwargs: {'articles': [], 'source': 'fixture'})
    monkeypatch.setattr(tools, '_search', lambda query: '未获得可核验补充材料。')
    monkeypatch.setattr(synthesis, '_invoke_structured', forbidden)
    monkeypatch.setenv('LANGGRAPH_EXECUTE_LIVE_TOOLS', 'true')
    monkeypatch.setenv('JINA_ENRICH_EVIDENCE', 'false')
    state = asyncio.run(GraphRunner.create().ainvoke(thread_id='macro-selector-full-graph', query=QUERY, output_mode='chat'))
    assert calls == [{'series_id': None, 'indicators': ['nonfarm_payroll_change', 'unemployment'], 'as_of': None}]
    assert state['trace']['analysis']['role'] == 'deterministic_renderer'
    assert not any(step['name'] == 'macro_agent' for step in state['plan_ir']['steps'])
