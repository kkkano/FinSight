"""核查默认交付、一次追加与报告版本的真实服务合同。"""
from copy import deepcopy
import hashlib

import pytest

from backend.agent_runtime.envelope import ToolResult
from backend.agent_runtime.registry import ToolSpec, schema
from backend.agent_runtime.presentation import message_blocks
from backend.tests.test_runtime_event_contract import make_pipeline
from backend.tests.test_runtime_loop_contract import runtime_environment, text_turn, tool_turn


PASS = {"verdict": "pass", "findings": [], "coverage": [{"requirement": "说明价格", "met": True}]}
ANSWER = "合成报价为 42 美元。[1]"
FINDING = {"quote": ANSWER, "issue": "待确认的合成问题", "evidence": "来源 [1]", "suggestion": "核对原值"}


def quote_tool():
    return ToolSpec("get_stock_price", "合成报价", schema({"ticker": {"type": "string"}}, ["ticker"]),
        lambda args: ToolResult(status="ok", kind="quote", data={"ticker": args["ticker"], "price": 42},
            sources=[{"title": "合成价格", "url": "https://example.test/quote"}]), financial=True, enveloped=True)


def initial_turns():
    return [tool_turn(("quote", "get_stock_price", {"ticker": "TEST"})), text_turn(ANSWER)]


@pytest.mark.asyncio
async def test_data_answer_is_visible_before_review_and_review_is_persisted_by_default(make_pipeline):
    run = make_pipeline([*initial_turns(), tool_turn(("submit", "submit_review", PASS))],
                        tools={"get_stock_price": quote_tool()})
    events = [event async for event in run.stream]
    kinds = [event.get("runtime_type", event["type"]) for event in events]
    assert kinds.index("content.delta") < kinds.index("answer.completed") < kinds.index("review.started")
    assert kinds.index("review.finished") < kinds.index("done")
    final = events[-1]
    assert final["response"] == ANSWER and final["answer_status"] == "answered"
    review = [block for block in final["blocks"] if block["kind"] == "review"][0]["review"]
    assert review["status"] == "completed" and review["verdict"] == "pass"
    assert review["answer_sha256"] == hashlib.sha256(ANSWER.encode()).hexdigest()
    assert run.saved[-1]["blocks"] == message_blocks(final["blocks"])
    assert all(set(tool["function"]["name"] for tool in call["tools"]) <= {"read_data", "run_python", "submit_review"}
               for call in run.model.inputs[2:])


@pytest.mark.asyncio
async def test_concept_answer_without_data_has_no_review_call(make_pipeline):
    run = make_pipeline([text_turn("这是概念说明。")])
    events = [event async for event in run.stream]
    assert len(run.model.inputs) == 1 and not any(event["type"].startswith("review.") for event in events)
    assert events[-1]["response"] == "这是概念说明。"


@pytest.mark.asyncio
async def test_chat_findings_only_annotate_and_never_replace_text(make_pipeline):
    review = {**PASS, "verdict": "revise", "findings": [FINDING]}
    run = make_pipeline([*initial_turns(), tool_turn(("submit", "submit_review", review))],
                        tools={"get_stock_price": quote_tool()})
    events = [event async for event in run.stream]
    assert events[-1]["response"] == ANSWER and len(run.model.inputs) == 3
    assert events[-1]["quality"]["state"] == "warn"
    assert not any(event["type"] == "content.revised" for event in events)


@pytest.mark.asyncio
async def test_unmet_coverage_appends_once_preserving_transcript_and_then_rechecks(make_pipeline):
    missing = {"verdict": "insufficient", "findings": [], "coverage": [{"requirement": "交付计算", "met": False}]}
    run = make_pipeline([*initial_turns(), tool_turn(("submit-1", "submit_review", missing)),
        text_turn("补充交付内容。"), tool_turn(("submit-2", "submit_review", missing))],
        tools={"get_stock_price": quote_tool()})
    events = [event async for event in run.stream]
    final = events[-1]
    assert final["response"] == ANSWER + "\n\n补充交付内容。"
    assert len(run.model.inputs) == 5 and len(final["reviews"]) == 2
    assert final["reviews"][1]["supersedes_review_id"] == final["reviews"][0]["review_id"]
    assert any(item.get("tool_call_id") == "quote" for item in run.model.inputs[3]["messages"])
    assert any(item["content"] == ANSWER for item in run.model.inputs[3]["messages"] if item["role"] == "assistant")
    assert not any(event["type"] == "content.revised" for event in events)
    assert any(reason["code"] == "unmet_requirements" for reason in final["quality"]["reasons"])


@pytest.mark.asyncio
@pytest.mark.parametrize("report", [False, True])
async def test_followup_token_limit_delivers_original_answer_and_review_as_partial(make_pipeline, monkeypatch, report):
    from backend.agent_runtime.limits import CapacityExceeded, TokenReservations

    original_reserve = TokenReservations.reserve
    calls = []

    async def reserve(self, count):
        calls.append(count)
        if len(calls) == 4:
            raise CapacityExceeded("run_token_budget_exhausted")
        return await original_reserve(self, count)

    monkeypatch.setattr(TokenReservations, "reserve", reserve)
    review = {"verdict": "revise" if report else "insufficient", "findings": [FINDING] if report else [],
              "coverage": [{"requirement": "尚未交付的计算", "met": False}]}
    run = make_pipeline([*initial_turns(), tool_turn(("submit", "submit_review", review))],
                        tools={"get_stock_price": quote_tool()}, output_mode="report" if report else "chat")
    events = [event async for event in run.stream]
    final = events[-1]
    assert final["type"] == "done" and final["answer_status"] == "partial"
    assert final["response"] == ANSWER and len(final["reviews"]) == 1
    assert len(run.model.inputs) == 3
    assert final["metrics"]["stopped"] == ("revision_token_budget" if report else "continuation_token_budget")
    assert any(reason["code"] == "run_budget_exhausted" for reason in final["quality"]["reasons"])
    assert not report or final["report"] is None and final["quality_blocked"]


@pytest.mark.asyncio
async def test_report_revision_is_model_generated_keeps_original_and_publishes_after_recheck(make_pipeline):
    revised = "重新核对后，合成报价为 42 美元。[1]"
    review = {**PASS, "verdict": "revise", "findings": [FINDING]}
    indexed = []
    run = make_pipeline([*initial_turns(), tool_turn(("submit-1", "submit_review", review)),
        text_turn(revised), tool_turn(("submit-2", "submit_review", PASS))], output_mode="investment_report",
        tools={"get_stock_price": quote_tool()}, index_report=lambda **kwargs: indexed.append(deepcopy(kwargs)) or True)
    events = [event async for event in run.stream]
    final = events[-1]
    assert final["response"] == revised and final["report_revision"]["original"] == ANSWER
    texts = [block for block in final["blocks"] if block["kind"] == "text"]
    assert [block["content"] for block in texts] == [ANSWER, revised]
    assert texts[1]["revision_of"] == [texts[0]["id"]]
    assert final["publishable"] is True and len(indexed) == 1
    assert indexed[0]["report"]["sections"][0]["contents"][0]["content"] == revised
    assert len([event for event in events if event["type"] == "content.revised"]) == 1
    assert "get_stock_price" in {tool["function"]["name"] for tool in run.model.inputs[3]["tools"]}


@pytest.mark.asyncio
async def test_unavailable_review_preserves_report_draft_without_indexing(make_pipeline):
    indexed = []
    run = make_pipeline([text_turn("报告草稿。"), text_turn("没有提交协议")], output_mode="investment_report",
                        index_report=lambda **kwargs: indexed.append(kwargs))
    events = [event async for event in run.stream]
    final = events[-1]
    assert final["response"] == "报告草稿。" and final["blocked_report"]
    assert final["publishable"] is False and final["report"] is None and indexed == []
    assert final["quality"]["review"]["status"] == "unavailable"


@pytest.mark.asyncio
async def test_main_phase_timeout_keeps_streamed_prefix_in_answer_and_continuation_history(make_pipeline):
    async def expire_main(turn, chunk):
        if turn == 1 and chunk == 0:
            raise TimeoutError("main_phase_deadline")

    missing = {"verdict": "insufficient", "findings": [], "coverage": [{"requirement": "完整说明价格", "met": False}]}
    run = make_pipeline([tool_turn(("quote", "get_stock_price", {"ticker": "TEST"})),
        text_turn("原文价格为"), tool_turn(("review-1", "submit_review", missing)),
        text_turn("42 美元。"), tool_turn(("review-2", "submit_review", PASS))],
        tools={"get_stock_price": quote_tool()}, after_chunk=expire_main)
    events = [event async for event in run.stream]
    assert events[-1]["response"] == "原文价格为42 美元。"
    assert any(message.get("content") == "原文价格为" for message in run.model.inputs[3]["messages"])
    assert [block["content"] for block in events[-1]["blocks"] if block["kind"] == "text"] == ["原文价格为", "42 美元。"]
