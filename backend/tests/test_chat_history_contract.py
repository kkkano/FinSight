from backend.api.chat_router import _attach_session_history, _request_history_for_context
from backend.api.schemas import ChatMessage


class _Turn:
    def __init__(self, query, response, metadata=None):
        self.query = query
        self.response = response
        self.metadata = metadata or {}


class _Manager:
    def get_last_n_turns(self, _limit):
        return [
            _Turn("分析 NVDA", "NVDA 当前重点看估值。", {"tickers": ["NVDA"]}),
        ]


def test_request_history_normalizes_visible_messages():
    history = _request_history_for_context(
        [
            ChatMessage(role="user", content="  分析   NVDA  "),
            ChatMessage(role="assistant", content="  重点看估值。  "),
        ]
    )

    assert history == [
        {"role": "user", "content": "分析 NVDA"},
        {"role": "assistant", "content": "重点看估值。"},
    ]


def test_attach_session_history_prefers_client_and_restores_verified_tickers():
    history = [
        ChatMessage(role="user", content="分析 NVDA"),
        ChatMessage(role="assistant", content="NVDA 当前重点看估值。"),
        ChatMessage(role="user", content="那风险呢？"),
    ]

    context = _attach_session_history({"view": "chat"}, _Manager(), history)

    assert context["view"] == "chat"
    assert context["session_history"] == [
        {"role": "user", "content": "分析 NVDA", "tickers": "NVDA"},
        {"role": "assistant", "content": "NVDA 当前重点看估值。"},
        {"role": "user", "content": "那风险呢？"},
    ]
