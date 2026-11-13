"""到期投影消费真实步骤产物，保留事实和缺项，不新增模型或网络工作。"""
import pytest

from backend.graph.execution.partial_delivery import build_partial_delivery
from backend.services.run_context import RunContext


@pytest.mark.asyncio
async def test_deadline_projection_keeps_verified_quote_and_unfinished_requirement(monkeypatch):
    from backend.graph.synthesis import research_synthesis

    async def forbidden_model(**_kwargs):
        pytest.fail("截止时间后启动了模型")

    monkeypatch.setattr(research_synthesis, "_invoke_structured", forbidden_model)
    run = RunContext.create(owner="alice", entry="chat")
    requirements = [
        {"requirement_id": "quote", "source_text": "价格", "metric": "quote", "kind": "fact_attribute",
         "subject": "AAPL", "evidence_kinds": ["price_snapshot"], "requires_analysis": False},
        {"requirement_id": "cash", "source_text": "经营现金流", "metric": "operating_cash_flow", "kind": "fact_attribute",
         "subject": "AAPL", "evidence_kinds": ["capital_allocation"], "requires_analysis": False},
    ]
    task = {"id": "task", "title": "AAPL", "tickers": ["AAPL"], "subject_label": "AAPL", "subject_type": "company",
            "operation": {"name": "qa"}, "priority": 0, "order_index": 0, "request_frame_id": "frame",
            "render_kind": "single", "render_group_id": "frame", "requirements_status": "confirmed",
            "required_evidence": ["price_snapshot", "capital_allocation"], "answer_requirements": requirements}
    run.compiled_state = {"tasks": [task], "understanding": {"requirements_status": "confirmed",
        "semantic_contract": {"status": "confirmed", "tasks": [task]}}, "subject": {"tickers": ["AAPL"]}}
    run.record_step({"id": "price", "name": "get_stock_price", "kind": "tool", "task_ids": ["task"],
        "inputs": {"ticker": "AAPL"}, "evidence_kinds": ["price_snapshot"]}, {
            "status_reason": "done", "output": {"ticker": "AAPL", "price": 100, "currency": "USD",
                "as_of": "2026-10-08", "source": "fixture", "market_session": "regular_close"}})
    run.finish("timed_out")
    result = await build_partial_delivery(run)
    assert result["answer_status"] == "partial" and result["publishable"] is False
    assert "100 USD" in result["response"]
    assert result["has_supported_content"] is True
    assert result["research_result"]["evidence_index"]
    assert any(row["requirement_id"] == "cash" for row in result["task_results"][0]["missing_requirements"])


@pytest.mark.asyncio
async def test_unconfirmed_original_question_cannot_be_replaced_by_seeded_valuation():
    query = "比较 ALFA 和 BETA 最近完整财年的营收及同比，再分析估值"
    tasks = [{"id": ticker, "title": ticker, "tickers": [ticker], "subject_label": ticker, "subject_type": "company",
              "operation": {"name": "price"}, "priority": index, "order_index": index,
              "request_frame_id": ticker, "render_kind": "single", "render_group_id": ticker,
              "required_evidence": ["price_snapshot"], "answer_requirements": [{"requirement_id": "legacy-valuation",
                  "kind": "fact_attribute", "metric": "quote", "dimension": "valuation_reasonableness",
                  "requires_analysis": False, "evidence_kinds": ["price_snapshot"]}]} for index, ticker in enumerate(["ALFA", "BETA"])]
    run = RunContext.create(owner="public", entry="chat")
    run.compiled_state = {"query": query, "tasks": tasks, "subject": {"tickers": ["ALFA", "BETA"]},
                          "understanding": {"requirements_status": "deterministic_fallback",
                              "semantic_contract": {"status": "unconfirmed", "query": query, "tasks": []}}}
    for ticker in ["ALFA", "BETA"]:
        run.record_step({"id": ticker, "name": "get_stock_price", "kind": "tool", "task_ids": [ticker],
                         "inputs": {"ticker": ticker}, "evidence_kinds": ["price_snapshot"]}, {
                             "status_reason": "done", "output": {"ticker": ticker, "price": 100, "currency": "USD",
                                                                  "as_of": "2026-10-08", "source": "fixture"}})
    run.finish("timed_out")
    result = await build_partial_delivery(run)
    assert "100 USD" in result["response"] and query in result["response"]
    assert len(result["missing_requirements"]) == 1
    assert result["missing_requirements"][0]["source_text"] == query
    assert result["answer_status"] == "partial" and result["has_supported_content"] and not result["publishable"]
    assert all(task["status"] == "partial" for task in result["task_results"])
    assert all(task["missing_requirements"][0]["reason"] == "request_contract_unconfirmed" for task in result["task_results"])


@pytest.mark.asyncio
async def test_deadline_without_facts_returns_recoverable_nonblank_text():
    run = RunContext.create(owner="public", entry="chat")
    run.finish("timed_out")
    result = await build_partial_delivery(run)
    assert result["answer_status"] == "unavailable" and not result["publishable"]
    assert result["response"].strip() and "运行记录已保留" in result["response"]


@pytest.mark.asyncio
async def test_actual_compiler_exit_connects_deadline_content_v2_and_safe_diagnostics(monkeypatch):
    import importlib
    from backend.services.run_context import run_context_scope
    from backend.graph.nodes.route_request import route_request
    async def failed(_state, _seed):
        return None, {"status": "unconfirmed", "validation_code": "request_understanding_timeout",
                      "raw_response": "fixture-private", "provider_attempts": 1}
    monkeypatch.setattr(importlib.import_module("backend.graph.nodes.route_request"), "extract_semantic_requirements", failed)
    run = RunContext.create(owner="public", entry="chat")
    with run_context_scope(run):
        compiled = await route_request({"query": "EXM最近完整财年营收同比"})
    assert compiled["tasks"] and compiled["tasks"][0]["required_evidence"] == ["document_context"]
    run.finish("timed_out")
    result = await build_partial_delivery(run)
    assert result["graph"]["trace"]["request_requirements"]["validation_code"] == "request_understanding_timeout"
    assert "fixture-private" not in str(result["graph"])
    assert result["content_contract_version"] == result["quality"]["content_contract_version"] == "research_content.v2"
    assert result["content_status"] == result["quality"]["content_status"] == "unavailable"
    assert result["response"].strip() and not result["publishable"]
