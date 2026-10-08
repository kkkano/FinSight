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
