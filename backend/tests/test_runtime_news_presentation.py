"""新闻解释、文章标题与能力验证活动的交付回归。"""
import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.agent_runtime import model as model_module, service
from backend.agent_runtime.completeness import ResearchCompleteness
from backend.agent_runtime.data import RunData
from backend.agent_runtime.fact_answer import factual_answer
from backend.agent_runtime.tools import ToolSpec, schema
from backend.api.execution_router import _native_pipeline_with_preflight
from backend.services.run_context import RunContext
from backend.tests.test_agent_runtime import call, cfg, finish
from backend.tests.test_runtime_answer_verification import pipeline

NEWS = [{"headline": "NVIDIA expands a computing partnership", "url": "https://example.com/nvidia-update",
    "published_at": "2026-11-09T09:00:00Z", "source": "Yahoo", "summary": "The company announced an expanded partnership."}]


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("FINSIGHT_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("FINSIGHT_RUNTIME_QUOTA_DB", str(tmp_path / "quota.sqlite"))
    monkeypatch.setenv("FINSIGHT_ACTION_STORE", str(tmp_path / "actions.sqlite"))
    monkeypatch.setenv("FINSIGHT_AGENT_MIN_REQUEST_INTERVAL_SECONDS", "0")
    monkeypatch.setattr(model_module, "_CAPABILITIES", {})


def test_headline_and_existing_article_title_survive_source_metadata():
    data = RunData("u", "s", "r", "NVDA新闻")
    ref = data.record("get_company_news", {"ticker": "NVDA"}, NEWS)
    source = next(row for row in data.sources.values() if row.get("url") == NEWS[0]["url"])
    assert source["title"] == NEWS[0]["headline"]
    data.add_source({"url": NEWS[0]["url"], "source": "Yahoo"}, ref)
    assert data.sources[source["source_id"]]["title"] == NEWS[0]["headline"]


@pytest.mark.asyncio
async def test_readback_ui_shows_the_source_preview_without_changing_model_input():
    from backend.agent_runtime.loop import AgentRuntime
    from backend.tests.test_agent_runtime import FakeModel
    events = []
    async def emit(kind, payload, agent_id):
        events.append((kind, payload))
    context = RunContext.create(owner="readback", entry="chat", budget_seconds=90)
    context.quota_checker = lambda _: None
    runtime = AgentRuntime(context=context, session_id="s", query="NVDA新闻", model=FakeModel([]), emit=emit, tools={})
    ref = runtime.data.record("search", {"query": "NVDA news"}, "相关报道原文\n第二段内容")
    try:
        result = await runtime.executor.execute("read_evidence", {"data_ref": ref}, "read", "root", runtime.available_tools("root", "research_lead"))
        preview = next(payload["output_preview"] for kind, payload in events if kind == "tool.result")
        assert preview["preview"] == "相关报道原文\n第二段内容"
        assert preview["offset"] == 0 and "content" not in preview
        assert '"tool": "search"' in result["result"]["content"]
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_local_news_verification_failure_keeps_chinese_explanation(monkeypatch):
    news = ToolSpec("get_company_news", "公司新闻", schema({"ticker": {"type": "string"}}, ["ticker"]), lambda _: NEWS, True)
    explanation = "值得关注的是公司扩大合作。这可能影响产品落地节奏，实际贡献仍需后续披露确认。"
    draft = explanation + "\n\nNVDA股价999美元。"
    events, _ = await pipeline(monkeypatch, [call("get_company_news", {"ticker": "NVDA"}), finish(draft), finish(draft)],
        {news.name: news}, query="NVDA最近有什么新闻")
    done = events[-1]
    assert explanation in done["response"]
    assert "999" not in done["response"]
    assert NEWS[0]["summary"] not in done["response"]
    assert not done["metrics"]["fact_fallback_used"]
    assert done["answer_status"] == "partial"


@pytest.mark.parametrize(("query", "allowed"), [("NVDA最近有什么新闻", False),
    ("NVDA最近有什么新闻，给我原文链接", False), ("NVDA只列出新闻标题和原文链接", True)])
def test_raw_news_catalogue_requires_an_explicit_list_request(query, allowed):
    data = RunData("u", "s", "r", query)
    data.record("get_company_news", {"ticker": "NVDA"}, NEWS)
    runtime = SimpleNamespace(query=query, report_title=None, data=data,
        completeness=ResearchCompleteness(query, [], {}), executor=SimpleNamespace(attempts=[]))
    assert bool(factual_answer(runtime)) is allowed


@pytest.mark.asyncio
async def test_cached_capability_does_not_emit_a_fake_probe_card(monkeypatch):
    monkeypatch.setattr(service, "resolve_model", cfg)
    calls = []

    async def probe(_context):
        calls.append(True)
        model_module._CAPABILITIES[cfg().identity()] = (time.monotonic() + 60, {"verified": True})

    async def research(**kwargs):
        yield {"type": "done", "seq": kwargs["initial_seq"] + 1, "response": "已完成"}

    monkeypatch.setattr(service, "preflight", probe)
    monkeypatch.setattr(service, "run_agent_pipeline", research)
    results = []
    for _ in range(2):
        context = RunContext.create(owner="probe-test", entry="chat", budget_seconds=90)
        results.append([event async for event in _native_pipeline_with_preflight(run_context=context,
            run_id=context.run_id, thread_id="s")])
    assert calls == [True]
    assert all(event["payload"]["summary"] for event in results[0][:-1])
    assert [event["type"] for event in results[1]] == ["done"]
    assert [event["seq"] for event in results[0]] == [1, 2, 3]


@pytest.mark.asyncio
async def test_probe_failure_settles_the_visible_activity(monkeypatch):
    monkeypatch.setattr(service, "cached_model_capability", lambda: None)

    async def probe(_context):
        raise HTTPException(422, detail={"code": "model_tool_calling_unsupported", "message": "此模型不支持工具调用。"})

    monkeypatch.setattr(service, "preflight", probe)
    context = RunContext.create(owner="probe-test", entry="chat", budget_seconds=90)
    async def archive():
        pass
    context.archive_usage = archive
    events = [event async for event in _native_pipeline_with_preflight(run_context=context, run_id=context.run_id, thread_id="s")]
    assert events[-2]["type"] == "activity.failed" and events[-2]["payload"]["reason"]
    assert events[-1]["type"] == "error"
