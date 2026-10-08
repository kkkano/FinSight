"""开放要求抽取与唯一 compiler 合同的定向回归；不调用外部模型。"""
import asyncio
from copy import deepcopy

import pytest
from langchain_core.messages import AIMessage

from backend.graph.intent.frame import intent_frame_from_legacy, legacy_understanding_from_frame
from backend.graph.nodes.policy_gate import policy_gate
from backend.graph.nodes.route_request import route_request
from backend.graph.planning.rule_planner import rule_based_planner
from backend.graph.request_compiler import compile_semantic_contract
from backend.graph.semantic_requirements import ExtractedRequest, SemanticRequest, extract_semantic_requirements, requires_semantic_extraction


QUERY = "分析 KO 最新已完成季度和最新完整财年的现金分红、股票回购、经营现金流与资本开支，计算股东回报后的现金结余；最近20个交易日累计收益、最大回撤与放量突破是否成立；也要报告它的量子护城河。不要比较竞品。"


def requirement(source, metric, *, scope=None, kind="fact_attribute", **fields):
    return {"source_text": source, "description": source, "metric": metric, "kind": kind,
            "subject": "KO", "subject_refs": ["ko"], "dimension": "unknown",
            "time_scope": scope or {"kind": "none"}, "capability_status": "supported", **fields}


def semantic_fixture():
    rows = []
    for kind, source in [("fiscal_quarter", "最新已完成季度"), ("fiscal_year", "最新完整财年")]:
        scope = {"kind": kind, "selection": "latest_complete", "count": 1, "completed_only": True, "source_text": source}
        for label, metric in [("现金分红", "dividends_paid"), ("股票回购", "repurchases_paid"),
                              ("经营现金流", "operating_cash_flow"), ("资本开支", "capital_expenditure"),
                              ("股东回报后的现金结余", "capital_allocation_surplus")]:
            rows.append(requirement(label, metric, scope=scope, kind="calculation" if metric == "capital_allocation_surplus" else "fact_attribute"))
    window = {"kind": "trading_sessions", "selection": "latest_complete", "count": 20,
              "completed_only": True, "source_text": "最近20个交易日"}
    for label, metric in [("累计收益", "cumulative_return"), ("最大回撤", "max_drawdown"), ("放量突破是否成立", "volume_breakout")]:
        rows.append(requirement(label, metric, scope=window, requires_analysis=metric == "volume_breakout"))
    rows.append(requirement("量子护城河", "unknown", metric_text="量子护城河", capability_status="unsupported"))
    constraint = {"constraint_type": "exclude_comparison", "source_text": "不要比较竞品", "description": "不要比较竞品"}
    rows.append(requirement("不要比较竞品", "unknown", kind="constraint", constraints=[constraint]))
    return SemanticRequest.model_validate({"subjects": [{"id": "ko", "type": "company", "label": "可口可乐", "tickers": ["KO"]}],
                                         "relation": "single", "requirements": rows, "constraints": [constraint]}).model_dump()


def compile_fixture(semantic=None):
    return compile_semantic_contract({"query": QUERY, "output_mode": "chat", "understanding": {"original_query": QUERY}},
                                     semantic or semantic_fixture(), {"status": "confirmed"})


def test_compiler_preserves_every_original_metric_and_unsupported_requirement():
    result = compile_fixture()
    raw = result["understanding"]["semantic_contract"]
    assert len(raw["requirements"]) == 15
    assert len(result["tasks"][0]["answer_requirements"]) == 15
    assert all(row["requires_explicit_binding"] for row in raw["requirements"])
    unknown = next(row for row in raw["requirements"] if row.get("metric_text") == "量子护城河")
    assert unknown["capability_status"] == "unsupported"
    assert unknown["metric"] == "unknown"
    result["tasks"][0]["answer_requirements"].pop()
    assert len(raw["tasks"][0]["answer_requirements"]) == 15
    assert len(result["trace"]["semantic_contract"]["requirements"]) == 15


def test_requirement_ids_are_stable_and_different_financial_periods_never_merge():
    first = compile_fixture()["tasks"][0]["answer_requirements"]
    second = compile_fixture()["tasks"][0]["answer_requirements"]
    assert [row["requirement_id"] for row in first] == [row["requirement_id"] for row in second]
    assert len({row["requirement_id"] for row in first}) == 15
    dividend = [row for row in first if row["metric"] == "dividends_paid"]
    assert {row["time_scope"]["kind"] for row in dividend} == {"fiscal_quarter", "fiscal_year"}


def test_new_evidence_kinds_reach_market_policy_and_exact_tool_arguments():
    state = {"query": QUERY, "output_mode": "chat", "ui_context": {"market": "US"}, **compile_fixture()}
    state.update(policy_gate(state))
    state.update(rule_based_planner(state))
    assert {"get_price_window_metrics", "get_sec_capital_allocation"} <= set(state["policy"]["allowed_tools"])
    capital = [step for step in state["plan_ir"]["steps"] if step["name"] == "get_sec_capital_allocation"]
    assert {step["inputs"]["frequency"] for step in capital} == {"quarterly", "annual"}
    assert all(step["inputs"]["limit"] == 2 and not step["optional"] for step in capital)
    window = next(step for step in state["plan_ir"]["steps"] if step["name"] == "get_price_window_metrics")
    assert window["inputs"] == {"ticker": "KO", "sessions": 20, "metrics": ["cumulative_return", "max_drawdown", "volume_breakout"],
                                "as_of": None, "price_basis": "close"}
    assert window["evidence_kinds"] == ["price_window"]
    assert state["trace"]["coverage_validator"]["status"] == "ok"


def test_intent_frame_round_trip_keeps_requirements_windows_and_original_snapshot():
    understanding = compile_fixture()["understanding"]
    frame = intent_frame_from_legacy(understanding)
    recovered = legacy_understanding_from_frame(frame)
    for key in ("answer_requirements", "time_scope", "constraints", "requirements_status", "request_text"):
        assert recovered["tasks"][0][key] == understanding["tasks"][0][key]
    assert recovered["semantic_contract"] == understanding["semantic_contract"]
    assert recovered["request_frames"] == understanding["request_frames"]


@pytest.mark.parametrize("mutation", ["source", "subject", "duplicate", "window"])
def test_invalid_extraction_cannot_compile_as_success(mutation):
    raw = semantic_fixture()
    if mutation == "source": raw["requirements"][0]["source_text"] = "用户没有说过的要求"
    if mutation == "subject": raw["requirements"][0]["subject_refs"] = ["unbound"]
    if mutation == "duplicate": raw["requirements"].append(deepcopy(raw["requirements"][0]))
    if mutation == "window": raw["requirements"][10]["time_scope"]["count"] = 0
    with pytest.raises(ValueError):
        compile_fixture(raw)


def test_missing_user_input_is_retained_as_an_unfulfilled_dependency():
    raw = semantic_fixture()
    raw["requirements"][0]["input_dependencies"] = ["position_cost_basis"]
    result = compile_fixture(raw)
    requirement = result["understanding"]["semantic_contract"]["requirements"][0]
    assert requirement["capability_status"] == "input_missing"
    assert requirement["input_dependencies"] == ["position_cost_basis"]


def test_known_metrics_project_capability_and_dimension_despite_model_tool_vocabulary_drift():
    raw = semantic_fixture()
    for row in raw["requirements"][:5]:
        row.update(dimension=row["metric"], capability_status="unsupported", evidence_kinds=["financial_statement"])
        row["time_scope"].update(kind="latest_quote", unit="quarter", as_of="latest_reported")
    result = compile_fixture(raw)
    canonical = result["tasks"][0]["answer_requirements"][:5]
    assert all(row["capability_status"] == "supported" for row in canonical)
    assert all(row["dimension"] == "fundamental_quality" for row in canonical)
    assert all(row["evidence_kinds"] == ["capital_allocation"] for row in canonical)
    assert all(row["time_scope"]["kind"] == "fiscal_quarter" and row["time_scope"]["as_of"] is None for row in canonical)
    assert result["trace"]["request_requirements"]["raw_semantic"]["requirements"][0]["time_scope"]["as_of"] == "latest_reported"
    assert canonical[0]["unmapped_evidence_kinds"] == ["financial_statement"]


def test_explicit_invalid_date_is_not_silently_replaced_with_latest():
    raw = semantic_fixture()
    raw["requirements"][0]["time_scope"].update(selection="explicit", as_of="last_reported")
    with pytest.raises(ValueError, match="request_as_of_invalid"):
        compile_fixture(raw)


def test_unsupported_scope_keeps_original_count_without_invalid_tool_plan():
    raw = semantic_fixture()
    raw["requirements"][10]["time_scope"]["count"] = 999
    result = compile_fixture(raw)
    requirement = result["tasks"][0]["answer_requirements"][10]
    assert requirement["capability_status"] == "unsupported"
    assert requirement["time_scope"]["count"] == 999


def test_model_schema_requests_semantics_without_code_owned_capability_fields():
    schema = ExtractedRequest.model_json_schema()
    fields = schema['$defs']['ExtractedRequirement']['properties']
    assert {'dimension', 'evidence_kinds', 'capability_status', 'requirement_id'}.isdisjoint(fields)
    assert schema['$defs']['RequiredInput']['properties']['input_key']['enum']


def test_quote_endpoint_uses_same_completed_window_and_canonical_attributes():
    query = "SPY 最近五个已结束交易日累计收益，同时列出终点收盘价和美元单位。"
    raw = {"subjects": [{"id": "spy", "type": "ticker", "label": "SPY", "tickers": ["SPY"]}], "requirements": [
        {"source_text": "累计收益", "description": "五个已结束交易日累计收益", "kind": "calculation", "metric": "cumulative_return", "subject": "SPY", "subject_refs": ["spy"],
         "time_scope": {"kind": "calendar_window", "count": 5, "selection": "latest_complete", "completed_only": True,
                        "unit": "trading_day", "source_text": "最近五个已结束交易日", "as_of": "latest_available", "period_start": "five_days_ago", "period_end": "latest_completed_day"}},
        {"source_text": "终点收盘价和美元单位", "description": "终点价格与币种", "kind": "fact_attribute", "metric": "quote", "subject": "SPY", "subject_refs": ["spy"],
         "attributes": ["currency_unit", "timestamp"], "price_role": "window_end", "time_scope": {"kind": "trading_sessions", "count": 1, "selection": "latest_complete", "completed_only": True, "source_text": "终点收盘价"}},
    ]}
    result = compile_semantic_contract({"query": query, "understanding": {"original_query": query}}, raw, {})
    requirements = result['tasks'][0]['answer_requirements']
    assert requirements[0]['time_scope']['kind'] == 'trading_sessions'
    assert requirements[0]['time_scope']['period_start'] is None and requirements[0]['time_scope']['as_of'] is None
    assert requirements[1]['time_scope']['kind'] == 'latest_quote'
    assert set(requirements[1]['attributes']) == {'currency', 'source_timestamp', 'end_close'}
    assert requirements[1]['evidence_kinds'] == ['price_window']
    assert result['tasks'][0]['subject_type'] == 'index'
    state = {'query': query, 'output_mode': 'chat', **result}
    state.update(policy_gate(state))
    plan = rule_based_planner(state)['plan_ir']
    assert [step['inputs']['sessions'] for step in plan['steps'] if step['name'] == 'get_price_window_metrics'] == [5]
    assert not any(step['name'] == 'get_stock_price' for step in plan['steps'])


def test_missing_report_and_company_inputs_clarify_without_dropping_unknown_requests():
    query = '更新这家公司报告，检查旧版结论。'
    raw = {'subjects': [], 'requirements': [{'source_text': '检查旧版结论', 'description': '检查旧报告结论', 'metric': 'unknown', 'metric_text': '检查旧版结论',
        'kind': 'explanation', 'input_dependencies': [{'input_key': 'previous_report', 'source_text': '旧版结论', 'source_ref': None}]}]}
    result = compile_semantic_contract({'query': query}, raw, {}, input_context={})
    assert result['understanding']['route'] == 'clarify'
    assert result['tasks'] == []
    assert result['blocked_tasks'][0]['answer_requirements'][0]['input_dependencies'] == ['previous_report']
    assert result['understanding']['semantic_contract']['requirements'][0]['metric_text'] == '检查旧版结论'
    assert '报告正文' in result['clarify']['question']


def test_structural_correction_reuses_selected_model_context_and_original_attempt_budget(monkeypatch):
    from importlib import import_module
    module = import_module('backend.graph.semantic_requirements')
    calls = []
    async def invoke(messages, **kwargs):
        calls.append(kwargs)
        kwargs['context'].budget.reserve_provider_attempt()
        raw = semantic_fixture()
        if len(calls) == 1:
            raw['requirements'][0]['input_dependencies'] = [':{']
        return {'raw': AIMessage(content='{}', response_metadata={'finish_reason': 'stop', 'model_name': 'selected-model'}), 'parsed': raw, 'parsing_error': None}
    monkeypatch.setattr(module, 'ainvoke_configured_llm', invoke)
    raw, diagnostics = asyncio.run(extract_semantic_requirements({'query': QUERY}, {}))
    assert raw is not None and len(calls) == 2
    assert calls[0]['context'] is calls[1]['context']
    assert all(call['max_tokens'] == 65536 and call['request_timeout'] == 1200 for call in calls)
    assert diagnostics['provider_attempts'] == 2 and diagnostics['schema_correction_attempts'] == 1
    assert diagnostics['semantic_attempts'][0]['requirements'][0]['input_dependencies'] == [':{']


def test_verified_document_url_and_source_input_survive_compilation_and_planning():
    query = '阅读这份报告，解释主要结论。'
    url = 'https://issuer.example.com/report.pdf'
    seed = {'query': query, 'subject': {'subject_type': 'research_doc', 'tickers': []}, 'tasks': [
        {'id': 'seed_doc', 'subject_type': 'research_doc', 'tickers': [], 'operation': {'name': 'summarize', 'params': {'url': url}}}]}
    raw = {'subjects': [{'id': 'doc', 'type': 'research_doc', 'label': '指定报告', 'tickers': []}], 'requirements': [
        {'source_text': '解释主要结论', 'description': '解释报告结论', 'kind': 'explanation', 'metric': 'document_question', 'subject_refs': ['doc'],
         'input_dependencies': [{'input_key': 'source_document', 'source_text': '这份报告', 'source_ref': url}]}]}
    result = compile_semantic_contract(seed, raw, {}, input_context={})
    task = result['tasks'][0]
    assert task['operation']['params']['url'] == url
    assert task['answer_requirements'][0]['input_dependencies'] == []
    assert task['answer_requirements'][0]['input_dependency_specs'][0]['available']
    state = {'query': query, 'output_mode': 'chat', **result}
    state.update(policy_gate(state))
    plan = rule_based_planner(state)
    fetch = next(step for step in plan['plan_ir']['steps'] if step['name'] == 'fetch_url_content')
    assert fetch['inputs']['url'] == url and fetch['evidence_kinds'] == ['document_context']
    assert plan['trace']['coverage_validator']['status'] == 'ok'


def test_forged_input_reference_cannot_mark_previous_report_as_available():
    query = '解释旧版结论。'
    raw = {'subjects': [{'id': 'doc', 'type': 'research_doc', 'label': '上一份报告', 'tickers': []}], 'requirements': [
        {'source_text': '旧版结论', 'description': '解释旧结论', 'kind': 'explanation', 'metric': 'document_question', 'subject_refs': ['doc'],
         'input_dependencies': [{'input_key': 'previous_report', 'source_text': '旧版结论', 'source_ref': 'invented-report-id'}]}]}
    result = compile_semantic_contract({'query': query}, raw, {}, input_context={'memory_context': {'current_report': {'id': 'real-report', 'markdown': '可核对的旧结论'}}})
    assert result['understanding']['route'] == 'clarify'
    assert result['blocked_tasks'][0]['answer_requirements'][0]['input_dependencies'] == ['previous_report']


def test_dividend_declaration_plans_official_statement_text_not_only_paid_cash():
    query = '核对 KO 正式公告派息金额与支付日期。'
    raw = {'subjects': [{'id': 'ko', 'type': 'company', 'label': 'KO', 'tickers': ['KO']}], 'requirements': [
        {'source_text': '正式公告派息金额与支付日期', 'description': '正式派息声明', 'kind': 'fact_attribute', 'metric': 'dividend_announcement', 'subject': 'KO', 'subject_refs': ['ko']} ]}
    state = {'query': query, 'output_mode': 'chat', **compile_semantic_contract({'query': query}, raw, {})}
    state.update(policy_gate(state))
    plan = rule_based_planner(state)['plan_ir']
    step = next(step for step in plan['steps'] if step['name'] == 'get_sec_material_events')
    assert step['inputs'] == {'ticker': 'KO', 'limit': 6, 'include_content': True}
    assert not step['optional'] and step['evidence_kinds'] == ['filing_context']


def test_mixed_market_comparison_keeps_both_local_and_us_disclosure_tools():
    query = '比较 KO 与 9988.HK 的最近完整季度营收。'
    raw = {'subjects': [{'id': 'ko', 'type': 'company', 'label': 'KO', 'tickers': ['KO']}, {'id': 'baba', 'type': 'company', 'label': '9988.HK', 'tickers': ['9988.HK']}],
        'relation': 'compare', 'requirements': [{'source_text': '营收', 'description': '同季度营收对比', 'kind': 'comparison', 'metric': 'revenue', 'subject_refs': ['ko', 'baba'],
        'time_scope': {'kind': 'fiscal_quarter', 'count': 1, 'selection': 'latest_complete', 'source_text': '最近完整季度'}}]}
    state = {'query': query, 'output_mode': 'chat', 'ui_context': {'market': 'US'}, **compile_semantic_contract({'query': query}, raw, {})}
    state.update(policy_gate(state))
    result = rule_based_planner(state)
    steps = result['plan_ir']['steps']
    assert any(step['name'] == 'get_local_market_filings' and step['inputs']['ticker'] == '9988.HK' for step in steps)
    assert any(step['name'] == 'get_sec_company_facts_quarterly' and step['inputs']['ticker'] == 'KO' for step in steps)
    assert not any(step['name'].startswith('get_sec_') and step['inputs']['ticker'] == '9988.HK' for step in steps)
    assert result['trace']['coverage_validator']['status'] == 'ok'


def test_price_measurement_maps_closing_role_without_parsing_user_wording():
    raw = {'subjects': [{'id': 'ko', 'type': 'company', 'label': 'KO', 'tickers': ['KO']}], 'requirements': [
        {'source_text': '现金分红', 'description': '不依赖原词的结构语义投影', 'kind': 'fact_attribute', 'metric': 'unknown',
         'measurement': 'price', 'price_role': 'latest_completed_close', 'subject': 'KO', 'subject_refs': ['ko'],
         'time_scope': {'kind': 'latest_quote', 'selection': 'latest_complete'}}]}
    # 原文不包含报价词；compiler 唯一依据为抽取出的测量对象与角色。
    compiled = compile_fixture(raw)['tasks'][0]['answer_requirements'][0]
    assert compiled['metric'] == 'quote' and compiled['capability_status'] == 'supported'
    assert set(compiled['attributes']) >= {'currency', 'source_timestamp'}
    assert 'end_close' not in compiled['attributes']


def test_unknown_event_window_metric_still_plans_future_event_calendar():
    raw = {'subjects': [{'id': 'ko', 'type': 'company', 'label': 'KO', 'tickers': ['KO']}], 'requirements': [
        {'source_text': '现金分红', 'description': '模型未给出规范指标名的事件窗口', 'kind': 'event_window', 'metric': 'unknown',
         'metric_text': '已确认事件', 'subject': 'KO', 'subject_refs': ['ko'],
         'time_scope': {'kind': 'calendar_window', 'selection': 'explicit', 'count': 90, 'unit': 'days', 'direction': 'future'}}]}
    compiled = compile_fixture(raw)['tasks'][0]['answer_requirements'][0]
    assert compiled['metric'] == 'news_catalysts' and compiled['raw_metric'] == 'unknown'
    assert compiled['capability_status'] == 'supported'
    assert {'news_context', 'event_calendar'} <= set(compiled['evidence_kinds'])


def test_unmapped_requirement_uses_confirmed_subject_without_reparsing_query():
    from backend.graph.intent.deterministic_engine import route_request_deterministic
    query = '只看 AVGO 的技术面：日线趋势和量子动能，不需要新闻或基本面。'
    seed = asyncio.run(route_request_deterministic({'query': query, 'output_mode': 'chat', 'ui_context': {}}, emit_understanding=False))
    raw = {'subjects': [{'id': 'avgo', 'type': 'company', 'label': 'AVGO', 'tickers': ['AVGO']}], 'requirements': [
        {'source_text': '量子动能', 'description': '无法映射的原始要求', 'kind': 'explanation', 'metric': 'unknown',
         'metric_text': '量子动能', 'subject': 'AVGO', 'subject_refs': ['avgo']}]}
    task = compile_semantic_contract(seed, raw, {'status': 'confirmed'})['tasks'][0]
    assert task['answer_requirements'][0]['capability_status'] == 'unsupported'
    assert set(task['required_evidence']) == {'document_context', 'company_profile', 'filing_context'}
    assert 'news_context' not in task['required_evidence']


def test_key_value_attributes_keep_only_registered_keys():
    raw = semantic_fixture()
    raw['requirements'][10]['attributes'] = ['confirmation_status:confirmed', 'data_frequency:daily', 'currency']
    compiled = compile_fixture(raw)['tasks'][0]['answer_requirements'][10]
    assert 'confirmation_status' in compiled['attributes'] and 'currency' in compiled['attributes']
    assert not any(':' in item for item in compiled['attributes'])
    assert 'data_frequency' not in compiled['attributes'] and compiled['data_frequency'] == 'daily'


def test_quote_attribute_like_components_and_empty_attributes_are_normalized():
    raw = {'subjects': [{'id': 'ko', 'type': 'company', 'label': 'KO', 'tickers': ['KO']}], 'requirements': [
        {'source_text': '现金分红', 'description': '报价', 'kind': 'fact_attribute', 'metric': 'quote', 'measurement': 'price',
         'price_role': 'current', 'data_frequency': 'daily', 'subject': 'KO', 'subject_refs': ['ko'],
         'attributes': ['', 'is_after_hours'], 'components': ['currency', 'quote_timestamp', 'after_hours_flag', 'price'],
         'time_scope': {'kind': 'latest_quote', 'selection': 'latest'}}]}
    compiled = compile_fixture(raw)['tasks'][0]['answer_requirements'][0]
    assert compiled['components'] == []
    assert set(compiled['attributes']) == {'currency', 'source_timestamp', 'market_session'}
    assert compiled['data_frequency'] == 'unspecified'


@pytest.mark.parametrize('kind,expected', [('fact_attribute', False), ('calculation', False), ('explanation', True), ('comparison', True)])
def test_calculated_numeric_fact_does_not_inherit_model_analysis_flag(kind, expected):
    raw = semantic_fixture()
    raw['requirements'][10].update(kind=kind, requires_analysis=True)
    compiled = compile_fixture(raw)['tasks'][0]['answer_requirements'][10]
    assert compiled['requires_analysis'] is expected
    assert set(compiled['attributes']) >= {'price_basis', 'dividends_included'}


def test_unknown_quote_measurement_gets_one_structural_correction_not_silent_unsupported(monkeypatch):
    from importlib import import_module
    module = import_module('backend.graph.semantic_requirements')
    query = 'KO 的终点价格。'
    calls = []
    async def invoke(messages, **kwargs):
        calls.append(kwargs['context'])
        kwargs['context'].budget.reserve_provider_attempt()
        row = {'source_text': '终点价格', 'description': '价格终点', 'kind': 'fact_attribute', 'metric': 'unknown', 'metric_text': '终点价格',
               'subject': 'KO', 'subject_refs': ['ko'], 'time_scope': {'kind': 'latest_quote', 'selection': 'latest_complete'}}
        if len(calls) == 2:
            row.update(measurement='price', price_role='window_end')
        return {'raw': AIMessage(content='{}', response_metadata={'finish_reason': 'stop'}),
                'parsed': {'route': 'research', 'subjects': [{'id': 'ko', 'type': 'company', 'label': 'KO', 'tickers': ['KO']}], 'requirements': [row]}, 'parsing_error': None}
    monkeypatch.setattr(module, 'ainvoke_configured_llm', invoke)
    raw, diagnostics = asyncio.run(extract_semantic_requirements({'query': query}, {}))
    assert raw is not None and len(calls) == 2 and calls[0] is calls[1]
    assert diagnostics['validation_attempts'] == ['request_quote_measurement_inconsistent']
    assert raw['requirements'][0]['measurement'] == 'price'


def test_full_graph_keeps_only_requested_window_metric_and_skips_research_llm(monkeypatch):
    from importlib import import_module
    from backend.graph.runner import GraphRunner
    routing = import_module('backend.graph.nodes.route_request')
    tools = import_module('backend.langchain_tools')
    synthesis = import_module('backend.graph.synthesis.research_synthesis')
    query = '核对 QQQ 最近4个已结束交易日累计收益、终点价格、币种和源时间，列出是否包含分红。'
    scope = {'kind': 'trading_sessions', 'count': 4, 'selection': 'latest_complete', 'completed_only': True, 'source_text': '最近4个已结束交易日'}
    raw = {'subjects': [{'id': 'qqq', 'type': 'index', 'label': 'QQQ', 'tickers': ['QQQ']}], 'requirements': [
        {'source_text': '累计收益', 'description': '窗口累计收益', 'kind': 'fact_attribute', 'metric': 'cumulative_return', 'subject': 'QQQ', 'subject_refs': ['qqq'], 'time_scope': scope, 'requires_analysis': True},
        {'source_text': '终点价格、币种和源时间', 'description': '终点价格及属性', 'kind': 'fact_attribute', 'metric': 'unknown', 'measurement': 'price', 'price_role': 'window_end',
         'subject': 'QQQ', 'subject_refs': ['qqq'], 'time_scope': {'kind': 'latest_quote', 'selection': 'latest_complete', 'completed_only': True}},
        {'source_text': '是否包含分红', 'description': '收益口径', 'kind': 'fact_attribute', 'metric': 'cumulative_return', 'subject': 'QQQ', 'subject_refs': ['qqq'], 'time_scope': scope, 'requires_analysis': True},
    ]}
    async def extract(state, seed):
        return deepcopy(raw), {'status': 'confirmed'}
    calls, analytical_calls = [], []
    def window(ticker, sessions, metrics, as_of, price_basis):
        calls.append({'ticker': ticker, 'sessions': sessions, 'metrics': metrics, 'as_of': as_of, 'price_basis': price_basis})
        payload = {'ticker': ticker, 'subject': ticker, 'kind': 'price_window', 'sessions': 4, 'completed_only': True,
                   'metrics': {'cumulative_return': {'value': .12, 'base_close': 100, 'end_close': 112, 'base_date': '2026-09-28', 'end_date': '2026-10-02', 'intervals': 4}},
                   'bars': [{'date': day, 'close': close} for day, close in zip(['2026-09-28', '2026-09-29', '2026-09-30', '2026-10-01', '2026-10-02'], [100, 101, 99, 111, 112])],
                   'end_close': 112, 'currency': 'USD', 'price_basis': 'split_adjusted_close', 'dividends_included': False,
                   'source_timestamp': '2026-10-02', 'as_of': '2026-10-02', 'period_start': '2026-09-28', 'period_end': '2026-10-02',
                   'source': 'fixture', 'source_url': 'https://example.test/qqq', 'error': None, 'missing_metrics': [], 'missing_session_dates': [], 'observation_count': 4}
        payload['structured_data'] = dict(payload)
        return payload
    async def forbidden_analysis(**kwargs):
        analytical_calls.append(kwargs)
        raise AssertionError('标准计算与口径属性不能进入研究模型')
    monkeypatch.setattr(routing, 'extract_semantic_requirements', extract)
    monkeypatch.setattr(tools, '_get_price_window_metrics', window)
    monkeypatch.setattr(synthesis, '_invoke_structured', forbidden_analysis)
    monkeypatch.setenv('LANGGRAPH_EXECUTE_LIVE_TOOLS', 'true')
    monkeypatch.setenv('JINA_ENRICH_EVIDENCE', 'false')
    state = asyncio.run(GraphRunner.create().ainvoke(thread_id='numeric-measurement-full-graph', query=query, output_mode='chat'))
    window_step = next(step for step in state['plan_ir']['steps'] if step['name'] == 'get_price_window_metrics')
    assert window_step['inputs']['metrics'] == ['cumulative_return']
    assert calls == [window_step['inputs']]
    assert not any(step['name'] == 'get_stock_price' for step in state['plan_ir']['steps'])
    assert state['trace']['analysis']['role'] == 'deterministic_renderer' and analytical_calls == []
    assert all(not row['requires_analysis'] for row in state['understanding']['semantic_contract']['requirements'])


def test_complex_route_uses_confirmed_semantics_instead_of_regex_dimension_denominator(monkeypatch):
    from importlib import import_module
    routing = import_module("backend.graph.nodes.route_request")
    calls = []
    async def extract(state, seed):
        calls.append(state["query"])
        return semantic_fixture(), {"status": "confirmed", "actual_model": "selected-fixture"}
    monkeypatch.setattr(routing, "extract_semantic_requirements", extract)
    result = asyncio.run(route_request({"query": QUERY, "output_mode": "chat", "ui_context": {}}))
    assert calls == [QUERY]
    assert result["understanding"]["requirements_status"] == "confirmed"
    assert len(result["tasks"][0]["answer_requirements"]) == 15
    assert result["trace"]["request_requirements"]["actual_model"] == "selected-fixture"


def test_semantic_failure_falls_back_to_rule_plan_and_cannot_claim_complete(monkeypatch):
    from importlib import import_module
    from backend.report.quality_engine import evaluate_result_quality
    routing = import_module("backend.graph.nodes.route_request")
    async def fail(state, seed):
        return None, {"status": "unconfirmed", "error_code": "request_contract_unconfirmed"}
    monkeypatch.setattr(routing, "extract_semantic_requirements", fail)
    result = asyncio.run(route_request({"query": QUERY, "output_mode": "chat", "ui_context": {}}))
    assert result["tasks"]
    assert result["understanding"]["route"] != "clarify"
    assert result["understanding"]["requirements_status"] == "deterministic_fallback"
    assert result["understanding"]["semantic_contract"]["status"] == "unconfirmed"
    assert result["understanding"]["intent_frame"]["source"] == "deterministic_rules"
    assert result["trace"]["request_requirements"]["error_code"] == "request_contract_unconfirmed"
    quality = evaluate_result_quality(state={**result, "output_mode": "chat"})
    assert quality["answer_status"] != "answered"
    assert any(item["code"] == "REQUEST_REQUIREMENTS_UNCONFIRMED" and item["severity"] == "warn" for item in quality["reasons"])
    report_quality = evaluate_result_quality(state={**result, "output_mode": "investment_report"})
    assert report_quality["publishable"] is False


def test_selected_model_extractor_keeps_full_foreground_budget_and_usage_diagnostics(monkeypatch):
    from importlib import import_module
    module = import_module("backend.graph.semantic_requirements")
    observed = {}
    async def invoke(messages, **kwargs):
        observed.update(kwargs)
        return {"raw": AIMessage(content="{}", response_metadata={"model_name": "selected-step", "finish_reason": "stop"},
                                 usage_metadata={"input_tokens": 50, "output_tokens": 70, "total_tokens": 120}),
                "parsed": SemanticRequest.model_validate(semantic_fixture()), "parsing_error": None}
    monkeypatch.setattr(module, "ainvoke_configured_llm", invoke)
    monkeypatch.delenv("LANGGRAPH_REQUEST_MAX_TOKENS", raising=False)
    monkeypatch.delenv("LANGGRAPH_REQUEST_TIMEOUT_SEC", raising=False)
    raw, diagnostics = asyncio.run(extract_semantic_requirements({"query": QUERY}, {}))
    assert len(raw["requirements"]) == 15
    assert observed["max_tokens"] == 65536
    assert observed["request_timeout"] == 1200
    assert "model" not in observed and "preferred_model" not in observed
    assert diagnostics["actual_model"] == "selected-step"
    assert diagnostics["prompt_tokens"] == 50 and diagnostics["completion_tokens"] == 70


@pytest.mark.parametrize("query", ["SPY 最近5个交易日收益", "AAPL 与 MSFT 现在股价比较", "KO 盘前价格和源时间", QUERY])
def test_complex_price_requests_cannot_enter_quote_fastpath(query):
    assert requires_semantic_extraction(query)


@pytest.mark.parametrize("query", ["你好", "谢谢", "KO 当前股价是多少？", "what is the current price of KO?"])
def test_unambiguous_simple_turns_keep_fastpath(query):
    assert not requires_semantic_extraction(query)


@pytest.mark.parametrize("query", ["请给我一份游族网络的投研分析报告", "请生成一份游族网络的投研分析报告"])
def test_unmapped_research_uses_semantic_subject_for_discovery(query):
    semantic = {"subjects": [{"id": "company", "type": "company", "label": "游族网络", "tickers": ["002174.SZ"]}],
                "requirements": [{"source_text": query, "description": query, "kind": "explanation",
                                  "metric": "unknown", "subject": "002174.SZ", "subject_refs": ["company"]}]}
    state = {"query": query, "output_mode": "chat", "understanding": {"original_query": query}}
    state.update(compile_semantic_contract(state, semantic, {}))
    state.update(policy_gate(state))
    state.update(rule_based_planner(state))
    steps = state["plan_ir"]["steps"]
    assert {"search", "get_local_market_filings"} <= {step["name"] for step in steps}
    assert next(step for step in steps if step["name"] == "search")["inputs"]["query"] == f"002174.SZ {query}"
    assert state["tasks"][0]["answer_requirements"][0]["capability_status"] == "unsupported"


@pytest.mark.parametrize("ticker", ["600519.SS", "0700.HK"])
def test_financial_requirements_use_local_disclosure_producer(ticker):
    query = f"{ticker} 最新完整财年的经营现金流是多少？"
    semantic = {"subjects": [{"id": "company", "type": "company", "label": ticker, "tickers": [ticker]}],
                "requirements": [{"source_text": "经营现金流", "description": "经营现金流", "kind": "fact_attribute",
                                  "metric": "operating_cash_flow", "subject": ticker, "subject_refs": ["company"],
                                  "time_scope": {"kind": "fiscal_year", "count": 1, "source_text": "最新完整财年"}}]}
    state = {"query": query, "output_mode": "chat", "understanding": {"original_query": query}}
    state.update(compile_semantic_contract(state, semantic, {}))
    state.update(policy_gate(state))
    state.update(rule_based_planner(state))
    assert state["tasks"][0]["answer_requirements"][0]["capability_status"] == "supported"
    names = {step["name"] for step in state["plan_ir"]["steps"]}
    assert "get_local_market_filings" in names
    producer = next(step for step in state["plan_ir"]["steps"] if step["name"] == "get_local_market_filings")
    assert producer["inputs"]["include_financial_facts"] is True
    assert "get_sec_capital_allocation" not in names
    assert state["trace"]["coverage_validator"]["status"] == "ok"


def test_semantic_report_intent_overrides_default_chat_without_keyword_matching():
    query = "为 INTC 准备一份供投资委员会审议的完整研究材料"
    semantic = {"output_mode": "investment_report",
                "subjects": [{"id": "company", "type": "company", "label": "英特尔", "tickers": ["INTC"]}],
                "requirements": [{"source_text": query, "description": "默认报告范围：业务", "kind": "explanation",
                                  "metric": "business_model", "subject": "INTC", "subject_refs": ["company"]}]}
    state = {"query": query, "output_mode": "chat", "understanding": {"original_query": query}}
    state.update(compile_semantic_contract(state, semantic, {}))
    assert state["output_mode"] == "investment_report"
    assert state["request_frames"][0]["lane"] == "report"
    assert state["reply_contract"]["lane"] == "report_generation"


def test_empty_research_plan_is_not_coverage_success():
    from backend.graph.coverage_validator import validate_plan_coverage
    result = validate_plan_coverage(
        request_frame={"frame_id": "f", "lane": "research", "task_ids": ["task_1"], "evidence_obligations": [],
                       "render_contract": {"answer_requirements": [{"kind": "explanation", "metric": "unknown"}]}},
        plan_ir={"steps": []},
    )
    assert result["status"] == "missing"
    assert result["missing_requirements"][0]["reason"] == "research_evidence_not_planned"


def test_named_company_without_ticker_is_researched_by_name_instead_of_clarified():
    query = "请给我一份游族网络的投研分析报告"
    semantic = {"output_mode": "investment_report",
                "subjects": [{"id": "company", "type": "company", "label": "游族网络", "tickers": []}],
                "requirements": [{"source_text": query, "description": "默认报告范围：业务", "kind": "explanation",
                                  "metric": "business_model", "subject": None, "subject_refs": ["company"]}]}
    state = {"query": query, "output_mode": "chat", "understanding": {"original_query": query}}
    state.update(compile_semantic_contract(state, semantic, {}))
    assert state["understanding"]["route"] == "research"
    assert not state["blocked_tasks"]
    assert state["tasks"][0]["required_evidence"] == ["document_context"]
    state.update(policy_gate(state))
    state.update(rule_based_planner(state))
    search = next(step for step in state["plan_ir"]["steps"] if step["name"] == "search")
    assert "游族网络" in search["inputs"]["query"]
    assert not search["subject_tickers"]
    assert any(step["name"] == "deep_search_agent" for step in state["plan_ir"]["steps"])
    assert state["trace"]["planner"]["validated"] is True


def test_missing_coverage_keeps_other_executable_steps_without_claiming_validation():
    state = {"query": QUERY, "output_mode": "chat", **compile_fixture()}
    state.update(policy_gate(state))
    state["policy"]["allowed_tools"] = ["search"]
    state["policy"]["allowed_agents"] = []
    state.update(rule_based_planner(state))
    assert state["plan_ir"]["steps"]
    assert state["trace"]["planner"]["validated"] is False
    assert state["trace"]["planner"]["executable"] is True
    assert state["trace"]["coverage_validator"]["status"] == "missing"
