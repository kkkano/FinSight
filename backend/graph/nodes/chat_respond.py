# -*- coding: utf-8 -*-
"""
Lightweight chat-respond node.

Positioned between `decide_output_mode` and `resolve_subject` so greetings /
casual queries never enter the analytical pipeline.

Design:
- Pure rules, zero LLM.
- If query is greeting/casual -> write a short template reply, set
  `chat_responded=True`, route to END.
- If analytical -> pass through unchanged.
- Optional anti-pollution mode removes current casual HumanMessage from
  history to avoid memory contamination.
"""
from __future__ import annotations

import random
from typing import Any

from langchain_core.messages import RemoveMessage

from backend.graph.nodes.query_intent import is_casual_chat, is_greeting
from backend.graph.state import GraphState

# ==================== Reply templates ====================
_GREETING_REPLIES: list[str] = [
    "你好！有什么可以帮你分析的吗？可以告诉我股票代码或公司名称。",
    "嗨！需要我帮你分析什么股票或市场趋势吗？",
    "你好！我是 FinSight 金融分析助手，告诉我你想分析什么吧。",
]

_THANKS_REPLIES: list[str] = [
    "不客气！还有什么需要分析的吗？",
    "没问题，随时可以继续问我。",
]

_BYE_REPLIES: list[str] = [
    "再见！有需要随时回来找我。",
    "拜拜，祝投资顺利。",
]

_META_REPLIES: dict[str, str] = {
    "你是谁": "我是 FinSight 金融分析助手，可以帮你分析股票、新闻和市场趋势。",
    "你叫什么": "我叫 FinSight，是一个金融研究助手。",
    "你能做什么": "我可以分析股票、解读新闻、生成投资报告、比较公司基本面等。",
    "你会什么": "我擅长股票行情、技术面、基本面、新闻影响和投资报告分析。",
    "你几岁了": "我是 AI 助手，没有年龄。你可以把我当成随时在线的金融分析同事。",
    "你多大了": "我是 AI 助手，没有年龄。你可以把我当成随时在线的金融分析同事。",
    "who are you": "I'm FinSight, a financial analysis assistant.",
    "what can you do": "I can analyze stocks, news, and market trends.",
    "how old are you": "I'm an AI assistant, so I don't have an age.",
}

_FALLBACK_CASUAL: str = "我主要负责金融分析。你可以输入股票代码（如 AAPL）或让我分析一条新闻。"

# Whether to remove current casual HumanMessage from history.
_SKIP_CASUAL_MESSAGES: bool = True


def _pick_reply(query: str) -> str:
    cleaned = (query or "").strip().lower()
    stripped = cleaned.rstrip("!?？?。！，, \t")

    for pattern, reply in _META_REPLIES.items():
        if pattern in stripped:
            return reply

    if stripped in ("再见", "拜拜", "拜", "bye", "goodbye"):
        return random.choice(_BYE_REPLIES)

    if stripped in ("谢谢", "感谢", "多谢", "辛苦了", "thanks", "thank you", "thx", "ty"):
        return random.choice(_THANKS_REPLIES)

    if is_greeting(query):
        return random.choice(_GREETING_REPLIES)

    return _FALLBACK_CASUAL


def _build_casual_message_cleanup(state: GraphState) -> list[RemoveMessage]:
    """
    Remove the latest HumanMessage (current casual query) from state history.

    This prevents repeated greetings/small-talk from polluting planner/synthesize
    context in subsequent analytical turns.
    """
    messages = state.get("messages") or []
    if not messages:
        return []

    last_msg = messages[-1]
    msg_id = getattr(last_msg, "id", None)
    if not msg_id:
        return []
    return [RemoveMessage(id=msg_id)]


def chat_respond(state: GraphState) -> dict[str, Any]:
    """
    Intercept greetings/casual queries before subject resolution.
    """
    query = (state.get("query") or "").strip()

    if not is_casual_chat(query):
        return {"chat_responded": False}

    reply = _pick_reply(query)
    artifacts = {**(state.get("artifacts") or {}), "draft_markdown": reply}

    result: dict[str, Any] = {
        "chat_responded": True,
        "artifacts": artifacts,
    }

    if _SKIP_CASUAL_MESSAGES:
        removals = _build_casual_message_cleanup(state)
        if removals:
            result["messages"] = removals

    return result


__all__ = ["chat_respond"]
