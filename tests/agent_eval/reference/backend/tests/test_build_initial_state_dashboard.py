# -*- coding: utf-8 -*-
import importlib

from langchain_core.messages import AIMessage, HumanMessage

build_initial_state_module = importlib.import_module(
    "backend.graph.nodes.build_initial_state",
)
def test_initial_state_recovers_client_history_when_checkpoint_is_empty():
    updates = build_initial_state_module.build_initial_state(
        {
            "thread_id": "public:anonymous:test",
            "query": "那风险呢？",
            "messages": [],
            "ui_context": {
                "session_history": [
                    {"role": "user", "content": "分析 NVDA"},
                    {"role": "assistant", "content": "NVDA 当前重点看估值与波动。"},
                    {"role": "user", "content": "那风险呢？"},
                ]
            },
        }
    )

    messages = updates["messages"]
    assert [message.content for message in messages] == [
        "分析 NVDA",
        "NVDA 当前重点看估值与波动。",
        "那风险呢？",
    ]
    assert isinstance(messages[0], HumanMessage)
    assert isinstance(messages[1], AIMessage)
    assert messages[0].id.startswith("client-history-")


def test_initial_state_does_not_duplicate_client_history_with_checkpoint():
    updates = build_initial_state_module.build_initial_state(
        {
            "thread_id": "public:anonymous:test",
            "query": "继续",
            "messages": [HumanMessage(content="已有 checkpoint 历史")],
            "ui_context": {
                "session_history": [
                    {"role": "user", "content": "客户端重复历史"},
                ]
            },
        }
    )

    assert [message.content for message in updates["messages"]] == ["继续"]
