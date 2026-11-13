"""核查员使用真实循环；只替换模型、隔离计算和外部存储。"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import json
import time

import pytest
import pytest_asyncio
from pydantic import ValidationError

from backend.agent_runtime import loop, registry, verifier
from backend.agent_runtime.config import ModelConfig
from backend.agent_runtime.data import RunData
from backend.agent_runtime.envelope import Source, ToolResult
from backend.agent_runtime.model import ModelProtocolError
from backend.agent_runtime.registry import ToolSpec, schema
from backend.services.run_context import RunContext, current_run_context


ANSWER = "当前价格为 10.25 美元[1]。尚未交付走势图。"
PASS = {"verdict": "pass", "findings": [], "coverage": [{"requirement": "说明当前价格", "met": True}]}


def tool_turn(name, args, *, text="", reasoning=""):
    return [{"choices": [{"delta": {"content": text, "reasoning_content": reasoning,
        "tool_calls": [{"index": 0, "id": "call_" + name, "type": "function",
            "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}]},
        "finish_reason": "tool_calls"}], "usage": {"prompt_tokens": 30, "completion_tokens": 10}}]


def text_turn(text, finish="stop"):
    return [{"choices": [{"delta": {"content": text}, "finish_reason": finish}],
             "usage": {"prompt_tokens": 30, "completion_tokens": 10}}]


class ScriptedModel:
    def __init__(self, turns, name="fixture-research"):
        self.config = ModelConfig(name, "https://fixture.invalid/v1", "fixture-private-key",
                                  context_window=65536, max_output=1024)
        self.turns, self.inputs, self.contexts = deepcopy(turns), [], []

    async def stream(self, messages, tools, **kwargs):
        index = len(self.inputs)
        self.inputs.append({"messages": deepcopy(messages), "tools": deepcopy(tools), "kwargs": kwargs})
        self.contexts.append(current_run_context())
        assert index < len(self.turns), "核查超出了假模型脚本"
        for chunk in self.turns[index]:
            yield deepcopy(chunk)


class BlockedModel(ScriptedModel):
    def __init__(self):
        super().__init__([])
        self.entered, self.closed = asyncio.Event(), False

    async def stream(self, messages, tools, **kwargs):
        self.entered.set()
        try:
            await asyncio.Event().wait()
            yield {}
        finally:
            self.closed = True


class MemoryLimiter:
    def __init__(self):
        self.owners, self.active, self.settled = [], 0, []

    @asynccontextmanager
    async def slot(self, bucket, owner, maximum, **kwargs):
        self.owners.append(owner)
        self.active += 1
        try:
            yield
        finally:
            self.active -= 1

    def reserve_window(self, *args, **kwargs):
        return "fixture-reservation"

    def settle_window(self, reservation, actual):
        self.settled.append((reservation, actual))


@pytest_asyncio.fixture
async def make_runtime(monkeypatch):
    monkeypatch.setenv("FINSIGHT_AGENT_MIN_REQUEST_INTERVAL_SECONDS", "0")
    monkeypatch.setenv("FINSIGHT_AGENT_TOKEN_BUDGET", "300000")
    monkeypatch.setattr(RunData, "save", lambda self: None)
    parents, reviewers = [], []

    def reviewer_factory(**kwargs):
        runtime = loop.AgentRuntime(**kwargs)
        reviewers.append(runtime)
        return runtime

    monkeypatch.setattr(verifier, "AgentRuntime", reviewer_factory)

    def create(turns=None, *, model=None):
        events = []

        async def emit(kind, payload, agent_id):
            events.append((kind, deepcopy(payload), agent_id))

        model = model or ScriptedModel(turns or [])
        context = RunContext(owner="fixture-owner", entry="chat", run_id="fixture-run",
                             deadline=time.monotonic() + 120, quota_checker=lambda _: None)
        runtime = loop.AgentRuntime(context=context, session_id="fixture-session", query="说明价格并给出走势图",
            model=model, emit=emit, tools={}, limiter=MemoryLimiter(),
            history=[{"role": "user", "content": "不相关历史不进入核查"}])
        runtime._answer_parts = [(ANSWER, "stop")]
        runtime.reviewers, runtime.test_events = reviewers, events
        parents.append(runtime)
        return runtime

    yield create
    for runtime in parents:
        await runtime.close()


def add_data(runtime):
    return runtime.data.record("get_stock_price", {"ticker": "AAPL"}, {"rows": [{"price": 10.25}]},
        envelope=ToolResult(status="ok", kind="table", sources=[Source(title="测试报价", url="https://fixture.invalid/quote")]))


@pytest.mark.asyncio
async def test_review_reads_actual_data_and_calculates_with_shared_identity_without_rewriting(make_runtime, monkeypatch):
    runtime = make_runtime()
    handle = add_data(runtime)
    original = runtime.data.snapshot()
    report = {"verdict": "revise", "findings": [{"quote": "尚未交付走势图。", "issue": "用户要求的图表尚缺失。",
        "evidence": "当前产物清单为空。", "suggestion": "追加走势图。"}],
        "coverage": [{"requirement": "说明价格", "met": True}, {"requirement": "给出走势图", "met": False}]}
    code = "result = {'price': datasets['" + handle + "']['rows'][0]['price']}"
    runtime.model.turns = [tool_turn("read_data", {"handle": handle}),
        tool_turn("run_python", {"handles": [handle], "code": code}),
        tool_turn("submit_review", report, text="不得替换父正文", reasoning="不得公开的内部推理")]
    calculated = []

    async def calculate(data, requested_code, handles, *, timeout):
        assert data is runtime.data and requested_code == code and handles == [handle]
        assert 0 < timeout <= 45
        output = {"price": data.records[handle]["output"]["rows"][0]["price"]}
        ref = data.record("run_analysis_code", {"dataset_refs": handles}, output)
        calculated.append(ref)
        return {"status": "ok", "result": output, "data_refs": [ref]}

    monkeypatch.setattr(registry, "run_analysis_code", calculate)
    result = await verifier.review_answer(runtime, ANSWER, max_seconds=90)

    import hashlib
    assert result == {"status": "completed", **report, "review_id": result["review_id"], "data_refs": calculated,
                      "answer_sha256": hashlib.sha256(ANSWER.encode("utf-8")).hexdigest(), "supersedes_review_id": None}
    reviewer = runtime.reviewers[-1]
    assert reviewer.context is not runtime.context and reviewer.context.owner == runtime.context.owner
    assert reviewer.context.run_id == runtime.context.run_id and reviewer.session_id == runtime.session_id
    assert reviewer.context.usage is runtime.context.usage and reviewer.context.cancelled is runtime.context.cancelled
    assert reviewer.data is runtime.data and reviewer.budget is runtime.budget and reviewer.limiter is runtime.limiter
    assert reviewer.model is runtime.model and reviewer.context.deadline - reviewer.context.started_monotonic <= 45
    assert all(context is reviewer.context for context in runtime.model.contexts)
    assert runtime.budget.spent == 120 and runtime.budget.reserved == 0
    assert runtime.limiter.owners == [runtime.context.owner] * 3 and runtime.limiter.active == 0
    assert runtime.root_content == ANSWER and not runtime._closed and reviewer._closed
    assert all(runtime.data.records[key] == value for key, value in original["records"].items())
    assert runtime.data.sources == original["sources"] and runtime.data.artifacts == []
    first = runtime.model.inputs[0]
    assert {item["function"]["name"] for item in first["tools"]} == {"read_data", "run_python", "submit_review"}
    assert all(message["content"] != "不相关历史不进入核查" for message in first["messages"])
    context_input = json.loads(first["messages"][1]["content"])
    assert context_input["available_data"][0]["handle"] == handle
    task = json.loads(first["messages"][-1]["content"])
    assert task == {"query": runtime.query, "answer": ANSWER, "sources": original["sources"],
                    "artifacts": [], "additional_requirements": []}
    assert any("10.25" in message["content"] for message in runtime.model.inputs[1]["messages"] if message["role"] == "tool")
    assert all(agent_id == result["review_id"] for _, _, agent_id in runtime.test_events)
    assert [kind for kind, _, _ in runtime.test_events if kind.startswith("review.")] == ["review.started", "review.finished"]
    assert not any(kind.startswith(("content.", "reasoning.")) for kind, _, _ in runtime.test_events)
    public = json.dumps(runtime.test_events, ensure_ascii=False)
    assert "不得公开的内部推理" not in public and "不得替换父正文" not in public
    assert "fixture-private-key" not in public
    assert current_run_context() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("verdict", ["pass", "revise", "insufficient"])
async def test_only_structured_submission_produces_a_verdict(make_runtime, verdict):
    submitted = {**PASS, "verdict": verdict}
    runtime = make_runtime([tool_turn("submit_review", submitted)])
    result = await verifier.review_answer(runtime, ANSWER)
    assert result["status"] == "completed" and result["verdict"] == verdict
    assert result["coverage"] == PASS["coverage"]
    assert len(runtime.model.inputs) == 1 and runtime.root_content == ANSWER


@pytest.mark.asyncio
async def test_quote_must_exist_verbatim_and_rejection_keeps_the_original_answer(make_runtime):
    bad = {"verdict": "revise", "findings": [{"quote": "当前价格为10.25美元[1]。", "issue": "注错测试",
        "evidence": "原始价格", "suggestion": "替换正文"}], "coverage": []}
    runtime = make_runtime([tool_turn("submit_review", bad), *[text_turn("pass") for _ in range(3)]])
    result = await verifier.review_answer(runtime, ANSWER)
    assert result["status"] == "unavailable" and result["error_code"] == "review_invalid_submission"
    assert "verdict" not in result and runtime.root_content == ANSWER
    errors = [item.error.code for item, _ in runtime.reviewers[-1].registry._results.values() if item.error]
    assert errors == ["review_quote_not_in_answer"]
    assert runtime.reviewers[-1]._closed and not runtime.context.cancelled.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("submission", [
    {**PASS, "answer": "擅自改写"},
    {**PASS, "coverage": [{"requirement": "价格", "met": "true"}]},
    {**PASS, "coverage": [{"requirement": "价格", "met": True, "replacement": "擅自改写"}]},
    {**PASS, "findings": [{"quote": "10.25", "issue": "问题", "evidence": "来源", "suggestion": "建议", "replacement": "改写"}]},
    {"verdict": "pass", "findings": []},
])
async def test_invalid_submission_cannot_fall_back_to_pass_or_insufficient(make_runtime, submission):
    runtime = make_runtime([tool_turn("submit_review", submission), *[text_turn("资料不足") for _ in range(3)]])
    result = await verifier.review_answer(runtime, ANSWER)
    assert result["status"] == "unavailable" and result["error_code"] == "review_invalid_submission"
    assert "verdict" not in result and runtime.root_content == ANSWER


def test_review_models_forbid_extra_fields_and_require_structured_coverage():
    for model, args in [(verifier.Review, PASS), (verifier.Coverage, PASS["coverage"][0]),
                       (verifier.ReviewFinding, {"quote": "10.25", "issue": "问题", "evidence": "来源", "suggestion": "建议"})]:
        with pytest.raises(ValidationError):
            model.model_validate({**args, "rewrite": "不应接受"})
    with pytest.raises(ValidationError):
        verifier.Review.model_validate({**PASS, "coverage": ["已交付"]})


@pytest.mark.asyncio
@pytest.mark.parametrize("name,args", [
    ("propose_action", {"kind": "watchlist.add", "ticker": "AAPL"}),
    ("get_stock_price", {"ticker": "AAPL"}),
    ("render_chart", {"handle": "h_unknown", "title": "不能画图", "chart_type": "line", "x": "date", "series": [{"field": "price"}]}),
    ("mark_report", {"title": "不能改报告"}),
    ("spawn_agents", {"tasks": []}),
    ("search_memory", {"query": "不能新增检索"}),
])
async def test_reviewer_cannot_fetch_new_financial_data_write_or_render(make_runtime, name, args):
    runtime = make_runtime([tool_turn(name, args), tool_turn("submit_review", PASS)])
    invoked = []
    runtime.base_tools["get_stock_price"] = ToolSpec("get_stock_price", "测试金融工具",
        schema({"ticker": {"type": "string"}}, ["ticker"]), lambda args: invoked.append(args), financial=True)
    result = await verifier.review_answer(runtime, ANSWER)
    reviewer = runtime.reviewers[-1]
    errors = [item.error.code for item, _ in reviewer.registry._results.values() if item.error]
    assert errors == ["tool_not_allowed"] and invoked == []
    assert result["status"] == "completed" and runtime.root_content == ANSWER
    assert runtime.data.records == {} and runtime.data.artifacts == [] and runtime.actions == {}
    assert runtime.tool_count == 0 and runtime.observed_tickers == []


@pytest.mark.asyncio
async def test_review_stops_at_four_turns_without_interpreting_plain_text_as_submission(make_runtime):
    runtime = make_runtime()
    handle = add_data(runtime)
    runtime.model.turns = [tool_turn("read_data", {"handle": handle}) for _ in range(3)] + [text_turn("继续", "length")]
    result = await verifier.review_answer(runtime, ANSWER)
    assert result["status"] == "unavailable" and result["error_code"] == "review_turn_limit"
    assert "verdict" not in result and runtime.root_content == ANSWER
    assert len(runtime.model.inputs) == 4
    assert [tool["function"]["name"] for tool in runtime.model.inputs[-1]["tools"]] == ["submit_review"]
    assert runtime.root_content == ANSWER and runtime.reviewers[-1]._closed


@pytest.mark.asyncio
async def test_fourth_turn_can_only_submit_the_structured_review(make_runtime):
    runtime = make_runtime()
    handle = add_data(runtime)
    runtime.model.turns = [tool_turn("read_data", {"handle": handle}) for _ in range(3)] + [tool_turn("submit_review", PASS)]
    result = await verifier.review_answer(runtime, ANSWER)
    assert result["status"] == "completed" and result["verdict"] == "pass"
    assert len(runtime.model.inputs) == 4
    assert [tool["function"]["name"] for tool in runtime.model.inputs[-1]["tools"]] == ["submit_review"]
    assert runtime.root_content == ANSWER and runtime.reviewers[-1]._closed


@pytest.mark.asyncio
async def test_model_text_without_submit_review_is_unavailable(make_runtime):
    runtime = make_runtime([text_turn(json.dumps(PASS)) for _ in range(4)])
    result = await verifier.review_answer(runtime, ANSWER)
    assert result["status"] == "unavailable" and result["error_code"] == "review_turn_limit"
    assert "verdict" not in result and runtime.root_content == ANSWER


@pytest.mark.asyncio
async def test_missing_submission_is_corrected_only_by_a_model_tool_call(make_runtime):
    runtime = make_runtime([text_turn("核查通过"), tool_turn("submit_review", PASS)])
    result = await verifier.review_answer(runtime, ANSWER)
    assert result["status"] == "completed" and result["verdict"] == "pass"
    assert len(runtime.model.inputs) == 2
    reminder = json.loads(runtime.model.inputs[1]["messages"][-1]["content"])
    assert reminder["required_submission_tools"] == ["submit_review"]
    assert runtime.root_content == ANSWER


@pytest.mark.asyncio
async def test_review_timeout_releases_resources_without_cancelling_parent(make_runtime):
    model = BlockedModel()
    runtime = make_runtime(model=model)
    result = await verifier.review_answer(runtime, ANSWER, max_seconds=.05)
    assert result["status"] == "unavailable" and result["error_code"] == "review_timeout"
    assert model.entered.is_set() and model.closed and runtime.reviewers[-1]._closed
    assert runtime.limiter.active == 0 and runtime.budget.reserved == 0
    assert runtime.context.status == "running" and not runtime.context.cancelled.is_set()
    assert runtime.root_content == ANSWER and runtime.test_events[-1][0] == "review.finished"


@pytest.mark.asyncio
async def test_task_cancellation_propagates_and_cleans_up_reviewer(make_runtime):
    model = BlockedModel()
    runtime = make_runtime(model=model)
    task = asyncio.create_task(verifier.review_answer(runtime, ANSWER))
    await asyncio.wait_for(model.entered.wait(), timeout=2)
    task.cancel("fixture_user_cancelled")
    with pytest.raises(asyncio.CancelledError, match="fixture_user_cancelled"):
        await task
    assert model.closed and runtime.reviewers[-1]._closed
    assert runtime.limiter.active == 0 and runtime.budget.reserved == 0
    assert runtime.test_events[-1][1]["error_code"] == "review_cancelled"
    assert runtime.root_content == ANSWER and not runtime._closed


@pytest.mark.asyncio
async def test_parent_cancellation_is_not_returned_as_a_review_verdict(make_runtime):
    runtime = make_runtime([tool_turn("submit_review", PASS)])
    runtime.context.cancelled.set()
    with pytest.raises(asyncio.CancelledError):
        await verifier.review_answer(runtime, ANSWER)
    assert runtime.model.inputs == [] and runtime.reviewers[-1]._closed


@pytest.mark.asyncio
async def test_explicit_model_override_keeps_parent_model_and_user_budget(make_runtime):
    runtime = make_runtime()
    chosen = ScriptedModel([tool_turn("submit_review", PASS)], name="fixture-review")
    result = await verifier.review_answer(runtime, ANSWER, model=chosen)
    assert result["status"] == "completed" and runtime.model.inputs == [] and len(chosen.inputs) == 1
    reviewer = runtime.reviewers[-1]
    assert reviewer.model is chosen and reviewer.context.selected_model == "fixture-review"
    assert reviewer.context.owner == runtime.context.owner and reviewer.budget is runtime.budget
    assert runtime.context.status == "running" and runtime.budget.spent == 40


@pytest.mark.asyncio
async def test_review_cannot_extend_a_finished_parent_budget(make_runtime):
    runtime = make_runtime()
    runtime.context.finish("completed")
    result = await verifier.review_answer(runtime, ANSWER)
    assert result["status"] == "unavailable" and runtime.model.inputs == []
    assert runtime.context.status == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("code,expected", [("fixture-private-key", "review_model_error"), ("model_timeout", "review_timeout")])
async def test_model_failure_is_unavailable_without_exposing_exception_details(make_runtime, code, expected):
    class FailedModel(ScriptedModel):
        async def stream(self, *args, **kwargs):
            raise ModelProtocolError(code)
            yield {}

    runtime = make_runtime(model=FailedModel([]))
    result = await verifier.review_answer(runtime, ANSWER)
    assert result["status"] == "unavailable" and result["error_code"] == expected
    assert "fixture-private-key" not in json.dumps(runtime.test_events)
    assert runtime.reviewers[-1]._closed


def test_should_review_uses_actual_data_calls_and_ignores_control_calls():
    from types import SimpleNamespace
    runtime = SimpleNamespace(registry=SimpleNamespace(attempts=[]), base_tools={})
    assert verifier.should_review(runtime) is False
    runtime.registry.attempts.append({"name": "update_plan", "data_refs": []})
    assert verifier.should_review(runtime) is False
    runtime.registry.attempts.append({"name": "read_data", "data_refs": ["h_existing"]})
    assert verifier.should_review(runtime) is True
