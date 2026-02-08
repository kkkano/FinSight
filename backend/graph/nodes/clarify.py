# -*- coding: utf-8 -*-
from __future__ import annotations

import re

from backend.graph.state import GraphState


_GREETING_TOKENS = (
    "hi",
    "hello",
    "hey",
    "你好",
    "嗨",
    "哈喽",
)


def _is_greeting(query: str) -> bool:
    lowered = (query or "").strip().lower()
    if not lowered:
        return False
    if any(t in lowered for t in _GREETING_TOKENS):
        return True
    return bool(re.fullmatch(r"(hi|hello|hey)[!. ]*", lowered))


def clarify(state: GraphState) -> dict:
    """
    The only place allowed to emit clarification prompts.

    This node can "interrupt" the graph by setting `clarify.needed=True`.
    Runner will route to END when clarification is needed.
    """
    subject = state.get("subject") or {}
    subject_type = subject.get("subject_type") or "unknown"
    query = (state.get("query") or "").strip()
    output_mode = state.get("output_mode") or "brief"

    trace = state.get("trace") or {}

    # Default: no clarification needed.
    clarify_state = {
        "needed": False,
        "reason": "",
        "question": "",
        "suggestions": [],
    }

    if subject_type != "unknown":
        trace.update({"clarify": {"needed": False, "subject_type": subject_type}})
        return {"clarify": clarify_state, "trace": trace}

    # Interrupt cases (unknown subject)
    if not query:
        clarify_state.update(
            {
                "needed": True,
                "reason": "empty_query",
                "question": "请先输入你的问题（例如：分析这条新闻的影响 / AAPL 现在怎么看）。",
                "suggestions": ["输入你的问题", "或在 Dashboard 先选择一个对象（新闻/财报/公司）"],
            }
        )
    elif _is_greeting(query):
        clarify_state.update(
            {
                "needed": True,
                "reason": "greeting",
                "question": "你好！你想分析哪只股票或哪条新闻？",
                "suggestions": ["输入股票代码（例如：AAPL）", "或在 Dashboard 选择一条新闻/财报/文档"],
            }
        )
    else:
        clarify_state.update(
            {
                "needed": True,
                "reason": "unknown_subject",
                "question": "我需要你先选定分析对象（公司 / 新闻 / 财报 / 文档）。",
                "suggestions": [
                    "选择一条新闻（Dashboard 点选新闻卡片）然后再提问",
                    "输入或选择一个股票代码（例如：AAPL）",
                    "选择一份财报（filing）或研究文档（doc）",
                ],
            }
        )

    mode_hint = ""
    if output_mode == "investment_report":
        mode_hint = "\n\n> 你选择了「生成研报」模式：请先选定对象（公司/新闻/财报），我才能按模板生成研报。"

    markdown = "\n".join(
        [
            clarify_state["question"],
            "",
            "你可以这样做：",
            *[f"- {s}" for s in (clarify_state.get("suggestions") or [])],
        ]
    ).strip()
    markdown = markdown + mode_hint

    artifacts = state.get("artifacts") or {}
    artifacts = {**artifacts, "draft_markdown": markdown}

    trace.update({"clarify": {"needed": True, "reason": clarify_state["reason"], "subject_type": subject_type}})
    return {"clarify": clarify_state, "artifacts": artifacts, "trace": trace}


__all__ = ["clarify"]

