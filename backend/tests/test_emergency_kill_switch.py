"""P0-8: REPORTS_GENERATION_ENABLED=false 时报告生成必须立即停止"""


def test_kill_switch_helper_blocks_when_disabled(monkeypatch):
    monkeypatch.setenv("REPORTS_GENERATION_ENABLED", "false")
    from backend.api.chat_router import _generation_enabled

    assert _generation_enabled() is False


def test_kill_switch_helper_blocks_with_zero(monkeypatch):
    monkeypatch.setenv("REPORTS_GENERATION_ENABLED", "0")
    from backend.api.chat_router import _generation_enabled

    assert _generation_enabled() is False


def test_kill_switch_helper_allows_by_default(monkeypatch):
    monkeypatch.delenv("REPORTS_GENERATION_ENABLED", raising=False)
    from backend.api.chat_router import _generation_enabled

    assert _generation_enabled() is True
