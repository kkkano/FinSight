# -*- coding: utf-8 -*-
from __future__ import annotations

import re

from backend.graph.state import GraphState


def parse_operation(state: GraphState) -> dict:
    """
    Rule-first operation parsing.

    Phase 3: deterministic + testable.
    Later phases may use a constrained LLM classifier, but must keep a rules fallback.
    """
    query = (state.get("query") or "").strip()
    subject = state.get("subject") or {}
    subject_type = subject.get("subject_type") or "unknown"

    lowered = query.lower()

    def _match_any(tokens: tuple[str, ...]) -> bool:
        for t in tokens:
            # Short ASCII tokens (<=3 chars) need word-boundary match to avoid
            # substring false-positives like "ma" inside "macro"/"market".
            if len(t) <= 3 and t.isascii():
                if re.search(r"\b" + re.escape(t) + r"\b", lowered):
                    return True
            elif t in lowered:
                return True
        return False

    op = "qa"
    confidence = 0.4

    if _match_any(("vs", "对比", "比較", "比较", "相比", "哪个更", "哪個更")):
        op = "compare"
        confidence = 0.8
    elif _match_any(("影响", "影響", "冲击", "衝擊", "利好", "利空", "怎么影响", "如何影响")):
        # Impact analysis has priority over raw price/technical keywords (e.g. "影响股价").
        op = "analyze_impact"
        confidence = 0.75
    elif _match_any(("技术面", "技術面", "技术分析", "技術分析", "technical analysis", "macd", "rsi", "kdj", "均线", "ma", "k线", "k線", "支撑", "阻力")):
        # Technical asks should not be treated as generic "fetch latest news".
        op = "technical"
        confidence = 0.85
    elif _match_any(("股价", "股價", "现价", "現價", "报价", "報價", "行情", "price", "quote", "多少钱", "多少錢", "现在多少钱")):
        op = "price"
        confidence = 0.8
    elif _match_any(("总结", "總結", "概括", "摘要", "要点", "要點", "tl;dr")):
        op = "summarize"
        confidence = 0.75
    elif subject_type in ("filing", "research_doc") and _match_any(
        ("抽取", "提取", "指标", "指標", "营收", "收入", "利润", "毛利", "eps", "guidance")
    ):
        op = "extract_metrics"
        confidence = 0.7
    elif _match_any(("获取", "列出", "有哪些", "新闻", "最新", "发生了什么", "發生了什麼")):
        op = "fetch"
        confidence = 0.65
    else:
        # Slight bump if the query clearly asks a question.
        if re.search(r"[?？]$", query) or _match_any(("吗", "嗎", "什么", "什麼", "为何", "為何")):
            op = "qa"
            confidence = 0.55

    return {"operation": {"name": op, "confidence": confidence, "params": {}}}
