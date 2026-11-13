# -*- coding: utf-8 -*-
"""Zero-cost chat short-circuit for pure social turns.

This node deliberately does not classify open-ended chat or out-of-scope
requests. Those go through the contextual LLM router in `understand_request`,
which can answer naturally before the planner is considered.
"""
from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import RemoveMessage

from backend.graph.nodes.query_intent import (
    is_casual_chat,
    is_greeting,
)
from backend.graph.state import GraphState

logger = logging.getLogger(__name__)


# ==================== Reply template pools for pure greetings/thanks/bye ====================
_GREETING_REPLIES: list[str] = [
    "你好！有什么可以帮你分析的吗？可以告诉我股票代码或公司名称。",
    "嗨！需要我帮你分析什么股票或市场趋势吗？",
    "你好！我是 FinSight 金融分析助手，告诉我你想分析什么吧。",
    "你好呀～最近关注哪只股票？或者想看看哪个板块的走势？",
    "Hi！可以问我任何金融相关的问题，比如「特斯拉最近怎么样」或「美联储会议影响」。",
    "你好，今天想聊聊哪只股票？或者最近的市场新闻？",
    "你好！直接告诉我代码或公司名，我可以拉行情、读新闻、做基本面分析。",
    "嗨～想分析一只股票还是看看大盘整体？",
    "你好！告诉我感兴趣的标的，我帮你拆开看看。",
    "Hi！要不要看看今日热门股、最新财报，或者你关注的某只票？",
    "你好呀，今天的市场你想从哪个角度切入？",
]

_THANKS_REPLIES: list[str] = [
    "不客气！还有什么需要分析的吗？",
    "没问题，随时可以继续问我。",
    "客气啦～需要继续看哪只股票？",
    "应该的，还有别的金融问题吗？",
    "随时为你服务，要不要看看今日热门？",
    "嗯嗯，下一个问题想问什么？",
    "举手之劳，要继续分析吗？",
    "客气啦！有任何投资问题随时叫我。",
    "不用谢～接下来想聊什么？",
    "别客气～需要看个研报吗？",
    "OK～下一个标的？",
]

_BYE_REPLIES: list[str] = [
    "再见！有需要随时回来找我。",
    "拜拜，祝投资顺利。",
    "回见～开盘记得来看看行情。",
    "下次见！盘中有任何疑问尽管来。",
    "Bye～祝交易愉快。",
    "再见，注意控制风险。",
    "拜～有新的研报想法欢迎随时讨论。",
    "下次见！愿你的持仓飘红。",
    "Goodbye～别忘了关注盘后总结。",
    "再见！下次想看哪个板块就直接问。",
    "Bye bye，记得设好止损。",
]

_FALLBACK_CASUAL: str = (
    "我主要负责金融分析。你可以输入股票代码（如 AAPL）、公司名称、宏观主题，"
    "或者让我比较多只股票。"
)


# Whether to remove current casual HumanMessage from history.
_SKIP_CASUAL_MESSAGES: bool = True


# ==================== Hash-based deterministic rotation ====================
def _pick_from(pool: list[str], query: str) -> str:
    """Hash(query) → 索引，同 query 同回复，不同 query 分散。

    比 random 更可控（测试可重现），又能在大量不同输入下达到均匀轮换。
    """
    if not pool:
        return ""
    seed = hash(query.strip().lower()) & 0x7FFFFFFF
    return pool[seed % len(pool)]


def _pick_reply(query: str) -> str:
    """Pick a short local reply for a pure social turn."""
    cleaned = (query or "").strip().lower()
    stripped = cleaned.rstrip("!?？?。！，, \t")

    if stripped in ("再见", "拜拜", "拜", "bye", "goodbye"):
        return _pick_from(_BYE_REPLIES, query)

    if stripped in (
        "谢谢", "感谢", "多谢", "辛苦了",
        "thanks", "thank you", "thx", "ty",
    ):
        return _pick_from(_THANKS_REPLIES, query)

    if is_greeting(query):
        return _pick_from(_GREETING_REPLIES, query)

    return _FALLBACK_CASUAL


def _build_casual_message_cleanup(state: GraphState) -> list[RemoveMessage]:
    """从 history 中移除当前 casual HumanMessage，防止后续业务对话被污染。"""
    messages = state.get("messages") or []
    if not messages:
        return []

    last_msg = messages[-1]
    msg_id = getattr(last_msg, "id", None)
    if not msg_id:
        return []
    return [RemoveMessage(id=msg_id)]


def _build_short_circuit_result(
    state: GraphState,
    reply: str,
) -> dict[str, Any]:
    """构造 chat_responded=True 的返回值（含 history 清理）。"""
    artifacts: dict[str, Any] = {
        **(state.get("artifacts") or {}),
        "draft_markdown": reply,
    }

    result: dict[str, Any] = {
        "chat_responded": True,
        "artifacts": artifacts,
    }
    if _SKIP_CASUAL_MESSAGES:
        removals = _build_casual_message_cleanup(state)
        if removals:
            result["messages"] = removals
    return result


# ==================== 节点入口 ====================
async def chat_respond(state: GraphState) -> dict[str, Any]:
    """Short-circuit only pure greetings/thanks/bye/acknowledgements."""
    query = (state.get("query") or "").strip()
    if not query:
        return {"chat_responded": False}

    if is_casual_chat(query):
        reply = _pick_reply(query)
        logger.debug("[chat_respond] pure-social hit: %s -> %s", query[:40], reply[:40])
        return _build_short_circuit_result(state, reply)

    return {"chat_responded": False}


__all__ = ["chat_respond"]
