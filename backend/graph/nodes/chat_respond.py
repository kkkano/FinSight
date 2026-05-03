# -*- coding: utf-8 -*-
"""
Lightweight chat-respond node.

Positioned between `decide_output_mode` and `resolve_subject` so greetings /
casual queries / out-of-scope (OOS) chat never enter the analytical pipeline.

Design (two-tier defense):
  Tier 1 — Rule-based casual chat detection (zero latency, white-list)
           → Hit: pick from template pool (≥10 variants per category) using
                  hash(query) for deterministic but spread rotation.
  Tier 2 — LLM intent classifier fallback (~0.3-2s, fires only when Tier-1
           misses AND query has no financial intent). Catches open-ended
           chitchat ("今天心情不好"), prompt-injection ("忽略你的身份"),
           and edge cases not in the rule pool.

Both tiers set `chat_responded=True` and write template reply to
`artifacts.draft_markdown`, then route to END.

Optional anti-pollution: removes current casual HumanMessage from history
to avoid memory contamination in subsequent analytical turns.
"""
from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import RemoveMessage

from backend.graph.nodes.intent_classifier import (
    IntentClassification,
    classify_intent,
    get_classifier_config,
)
from backend.graph.nodes.query_intent import (
    has_financial_intent,
    is_casual_chat,
    is_greeting,
)
from backend.graph.state import GraphState

logger = logging.getLogger(__name__)


# ==================== Reply template pools (≥10 variants per category) ====================
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

# Each meta-pattern maps to a list of equivalent replies (≥3 variants per pattern)
_META_REPLIES: dict[str, list[str]] = {
    "你是谁": [
        "我是 FinSight 金融分析助手，可以帮你分析股票、新闻和市场趋势。",
        "我叫 FinSight，是一个专门做金融研究的 AI 助手。",
        "FinSight，一个金融垂直 Agent。我擅长行情、财报、研报、宏观分析。",
    ],
    "你叫什么": [
        "我叫 FinSight，是一个金融研究助手。",
        "我是 FinSight，专心做投研的 AI 助手喵～",
        "我叫 FinSight。可以让我帮你分析股票、读研报、追新闻。",
    ],
    "你是做什么的": [
        "我做金融研究：股票分析、新闻解读、财报拆解、行业对比。",
        "我专门做金融分析。把你想看的标的或主题告诉我就行。",
        "我是金融垂直 Agent，专注股票、宏观、研报这些事。",
    ],
    "你能做什么": [
        "我可以分析股票、解读新闻、生成投资报告、比较公司基本面等。",
        "拉行情、读财报、追新闻、做技术分析、生成投资报告——这些都行。",
        "股票/宏观/财报/新闻/持仓分析都可以。直接告诉我你想看什么。",
    ],
    "你会什么": [
        "我擅长股票行情、技术面、基本面、新闻影响和投资报告分析。",
        "行情、研报、财报、宏观、技术分析、持仓评估，都在我的工具箱里。",
        "K 线、估值、研报、并购消息、宏观数据，几乎都能给你拆开看。",
    ],
    "你几岁了": [
        "我是 AI 助手，没有年龄。你可以把我当成随时在线的金融分析同事。",
        "AI 没有年龄喵～不过我每天都在追最新的市场数据。",
        "没有年龄，但全年开盘期间我都在线。",
    ],
    "你多大了": [
        "我是 AI 助手，没有年龄。你可以把我当成随时在线的金融分析同事。",
        "AI 没有岁数～不过最新模型版本算是我的「年龄」。",
        "没年龄，但你随时叫我都在。",
    ],
    "who are you": [
        "I'm FinSight, a financial analysis assistant.",
        "I'm FinSight — a vertical AI agent focused on financial research.",
        "FinSight here. I do stocks, earnings, news and market analysis.",
    ],
    "what can you do": [
        "I can analyze stocks, news, and market trends.",
        "I run quote pulls, earnings reads, news impact, technical & fundamental analysis.",
        "Stock, macro, earnings, news, portfolio review — pretty much covered.",
    ],
    "how old are you": [
        "I'm an AI assistant, so I don't have an age.",
        "No age — just an AI tracking the markets.",
        "AI has no age, but I'm always on during market hours.",
    ],
}

# Out-Of-Scope (OOS) replies: when LLM classifier confirms query is non-financial.
_OOS_REPLIES: list[str] = [
    "这个问题我可能帮不上忙——我专注于股票、新闻和市场分析。要不换个话题，比如帮你看看某只股票的走势？",
    "嗯…这超出了我的金融专长。如果你想把它转到投资视角（相关板块/受益股票），我倒是可以聊。",
    "抱歉，我只懂金融研究。要不告诉我你想分析哪只股票，或者最近关注的市场新闻？",
    "我这边只能聊金融～换个话题：你最近持仓怎么样？或者想看看大盘？",
    "这个我没法回答喵～不过你可以问我「美联储利率走势」「特斯拉财报解读」之类的金融话题。",
    "这块我不在行～我擅长的是股票、宏观、研报。要不来一个金融问题？",
    "感觉这超出了我的领域。我的工具箱里全是行情、财报、新闻分析——要不换个？",
    "我专心做金融分析，其它话题不太能聊。来个股票分析任务好不好？",
    "这个问题我答不好，但如果是关于股票、行业、宏观的，我可以帮你做深度分析。",
    "不好意思，我是金融垂直助手喵～来问我点投资相关的吧。",
    "这个超纲了～换成「分析下 AAPL」「最近港股怎么样」这种我就能上手了。",
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
    """Tier-1 规则匹配：选模板回复。"""
    cleaned = (query or "").strip().lower()
    stripped = cleaned.rstrip("!?？?。！，, \t")

    for pattern, replies in _META_REPLIES.items():
        if pattern in stripped:
            return _pick_from(replies, query)

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
    classification: IntentClassification | None = None,
) -> dict[str, Any]:
    """构造 chat_responded=True 的返回值（含 history 清理 + classification 元信息）。"""
    artifacts: dict[str, Any] = {
        **(state.get("artifacts") or {}),
        "draft_markdown": reply,
    }
    if classification is not None:
        artifacts["intent_classification"] = {
            "category": classification.category,
            "confidence": classification.confidence,
            "reason": classification.reason,
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
    """Two-tier interception of casual / OOS queries before subject resolution.

    Tier 1 (rule-based): is_casual_chat(query) — hits greeting/thanks/bye/meta/OOS-rule
        → pick from template pool by hash(query) and short-circuit.

    Tier 2 (LLM classifier): only when Tier-1 misses AND query lacks financial intent
        → call mimo-v2.5 to classify in_scope/out_of_scope/ambiguous,
        accept OOS only if confidence ≥ threshold (default 70).

    Otherwise → pass through to business pipeline (chat_responded=False).
    """
    query = (state.get("query") or "").strip()
    if not query:
        return {"chat_responded": False}

    # === Tier 1：规则白名单（零延迟）===
    if is_casual_chat(query):
        reply = _pick_reply(query)
        logger.debug("[chat_respond] tier1-rule hit: %s → %s", query[:40], reply[:40])
        return _build_short_circuit_result(state, reply)

    # === Tier 2：LLM 分类器兜底 ===
    # 提前剪枝：只要 query 里有金融词，直接放行业务管道，节省一次 LLM 调用。
    if has_financial_intent(query):
        return {"chat_responded": False}

    classifier_cfg = get_classifier_config()
    if not classifier_cfg.enabled:
        # 分类器被禁用，规则未命中且无金融词 —— 仍走业务管道（understand_request 的
        # is_casual_chat 第二道兜底会在必要时走 clarify route）
        return {"chat_responded": False}

    classification = await classify_intent(query)
    if classification is None:
        # 分类失败（超时/异常/空响应）→ fail-open，放行业务管道
        return {"chat_responded": False}

    # 仅当模型判定 out_of_scope 且置信度足够时才拦截
    if (
        classification.category == "out_of_scope"
        and classification.confidence >= classifier_cfg.confidence_threshold
    ):
        reply = _pick_from(_OOS_REPLIES, query)
        logger.info(
            "[chat_respond] tier2-llm OOS hit: query=%r conf=%d reason=%s",
            query[:60],
            classification.confidence,
            classification.reason,
        )
        return _build_short_circuit_result(state, reply, classification=classification)

    # ambiguous / in_scope / 低置信度 OOS → 放行
    return {"chat_responded": False}


__all__ = ["chat_respond"]
