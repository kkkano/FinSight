import pytest
from pydantic import ValidationError

from backend.api.schemas import ChatRequest
from backend.api.session_context import _build_ui_context


def test_chat_handoff_context_is_explicitly_whitelisted_without_overwriting_view():
    request = ChatRequest.model_validate({
        "query": "分析 AAPL",
        "context": {
            "active_symbol": "AAPL",
            "view": "chat",
            "source_view": "dashboard",
            "source_tab": "technical",
            "ignored": "must not pass",
        },
    })

    assert _build_ui_context(request) == {
        "active_symbol": "AAPL",
        "view": "chat",
        "source_view": "dashboard",
        "source_tab": "technical",
    }


@pytest.mark.parametrize("source_tab", ["", "x" * 65, "news\nadmin"])
def test_chat_handoff_source_tab_rejects_invalid_values(source_tab: str):
    with pytest.raises(ValidationError):
        ChatRequest.model_validate({
            "query": "分析 AAPL",
            "context": {"source_view": "dashboard", "source_tab": source_tab},
        })
