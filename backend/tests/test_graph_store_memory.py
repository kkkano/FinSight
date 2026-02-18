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
    assert context["last_focus"]["ticker"] == "AAPL"
    assert context["last_focus"]["query"] == "请分析 AAPL 的投资机会"
    assert context["last_focus"]["summary"]
    assert context["last_focus"]["sentiment"] == "bullish"
    assert isinstance(context["recent_focuses"], list)
    assert len(context["recent_focuses"]) >= 1


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
