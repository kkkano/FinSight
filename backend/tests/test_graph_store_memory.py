import backend.graph.store as graph_store
from backend.graph.store import (
    load_memory_context,
    persist_memory_snapshot,
    resolve_user_id,
)
from backend.services.memory import MemoryService


def test_resolve_user_id_from_thread_id():
    assert resolve_user_id("public:alice:thread-1") == "alice"
    assert resolve_user_id("tenant:bob:abc") == "bob"
    assert resolve_user_id("no-segments") == "default_user"
    assert resolve_user_id("") == "default_user"


def test_persist_and_load_memory_snapshot(tmp_path):
    service = MemoryService(storage_path=str(tmp_path))
    thread_id = "public:test_user:thread-001"

    state = {
        "query": "请分析 AAPL 的投资机会",
        "subject": {"tickers": ["AAPL"]},
        "artifacts": {
            "render_vars": {
                "investment_summary": "AAPL 当前盈利质量稳定，估值处于历史中位附近。"
            }
        },
    }
    report = {"summary": "AAPL 基本面稳健，短期受业绩预期驱动。", "sentiment": "bullish"}

    assert persist_memory_snapshot(
        thread_id=thread_id,
        state=state,
        report=report,
        memory_service=service,
    )

    context = load_memory_context(thread_id=thread_id, memory_service=service)
    assert context["user_id"] == "test_user"
    assert "last_focus" not in context
    assert "last_report" not in context
    assert "recent_focuses" not in context

    current_focus = context["current_thread_focus"]
    assert current_focus["ticker"] == "AAPL"
    assert current_focus["query"] == state["query"]
    assert current_focus["summary"]
    assert current_focus["sentiment"] == "bullish"

    historical = context["historical_focus_memory"]
    assert historical["last_focus"]["ticker"] == "AAPL"
    assert isinstance(historical["recent_focuses"], list)
    assert len(historical["recent_focuses"]) >= 1


def test_persist_memory_snapshot_keeps_last_report_context(tmp_path):
    service = MemoryService(storage_path=str(tmp_path))
    thread_id = "public:test_user:thread-report"

    report = {
        "report_id": "rpt-ctx-001",
        "ticker": "AAPL",
        "title": "Apple investment report",
        "summary": "Apple report summary for follow-up chat.",
        "sentiment": "neutral",
        "generated_at": "2026-05-04T00:00:00Z",
        "sections": [{"title": "Risks"}, {"title": "Valuation"}],
        "risks": ["Valuation remains sensitive to rates.", "China demand can pressure revenue."],
    }

    assert persist_memory_snapshot(
        thread_id=thread_id,
        state={"query": "Build Apple report", "subject": {"tickers": ["AAPL"]}},
        report=report,
        memory_service=service,
    )

    context = load_memory_context(thread_id=thread_id, memory_service=service)
    last_report = context["current_report"]
    assert last_report["report_id"] == "rpt-ctx-001"
    assert last_report["summary"] == "Apple report summary for follow-up chat."
    assert last_report["risks"][0] == "Valuation remains sensitive to rates."

    assert context["current_thread_focus"]["last_report"]["report_id"] == "rpt-ctx-001"
    assert context["historical_focus_memory"]["last_report"]["report_id"] == "rpt-ctx-001"

    other_thread_context = load_memory_context(
        thread_id="public:test_user:different-thread",
        memory_service=service,
    )
    assert other_thread_context["current_thread_focus"] is None
    assert other_thread_context["current_report"] is None
    assert other_thread_context["historical_focus_memory"]["last_report"]["report_id"] == "rpt-ctx-001"


def test_memory_service_init_failure_only_warn_once(monkeypatch, caplog):
    def _raise_init(*args, **kwargs):
        raise RuntimeError("init failed")

    monkeypatch.setattr(graph_store, "MemoryService", _raise_init)
    monkeypatch.setattr(graph_store, "_memory_service", None)

    caplog.set_level("WARNING")
    assert graph_store._get_memory_service() is None  # noqa: SLF001
    assert graph_store._get_memory_service() is None  # noqa: SLF001

    warning_logs = [rec.message for rec in caplog.records if "init memory service failed" in rec.message]
    assert len(warning_logs) == 1
