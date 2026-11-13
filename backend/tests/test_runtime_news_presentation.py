"""新闻出处、读回投影与能力验证活动的交付回归。"""
import time
import pytest
from fastapi import HTTPException
from backend.agent_runtime import model as model_module, service
from backend.agent_runtime.data import RunData
from backend.api.execution_router import _native_pipeline_with_preflight
from backend.services.run_context import RunContext
from backend.tests.test_agent_runtime import cfg, runtime, execute

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


@pytest.mark.asyncio
async def test_readback_ui_shows_the_source_preview_without_changing_model_input(tmp_path):
    rt, events = runtime(tmp_path, [])
    original = "相关报道原文\n第二段内容"
    ref = rt.data.record("search", {"query": "NVDA news"}, original)
    try:
        result = await execute(rt, "read_data", {"handle": ref}, "read")
        payload = next(payload for kind, payload, _ in events if kind == "tool.result")
        assert payload["output_preview"]["content"] == original
        assert payload["output_preview"]["offset"] == 0
        assert original in result.data["content"] and result.data["next_offset"] == len(original)
        assert rt.data.records[ref]["output"] == original
    finally:
        await rt.close()
