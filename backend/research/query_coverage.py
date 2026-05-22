# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

_DIMENSION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "valuation": ("估值", "pe", "p/e", "pb", "ps", "市盈率", "市净率", "valuation", "multiple", "fair value"),
    "risk": ("风险", "下行", "不确定", "回撤", "risk", "downside", "uncertain", "bear"),
    "catalyst": ("催化", "未来三个月", "关注", "触发", "catalyst", "watch", "next", "upcoming"),
    "technical": ("技术", "rsi", "macd", "均线", "支撑", "阻力", "technical", "momentum"),
    "fundamental": ("基本面", "营收", "利润", "毛利", "现金流", "fundamental", "revenue", "margin", "cash flow"),
    "macro": ("宏观", "利率", "通胀", "fed", "macro", "rate", "inflation"),
    "price": ("价格", "股价", "报价", "price", "quote"),
    "news": ("新闻", "消息", "headline", "news"),
    "portfolio": ("组合", "持仓", "portfolio", "position", "allocation"),
    "holdings": ("13f", "form 4", "名人持仓", "机构持仓", "内部人", "insider", "holdings", "berkshire", "buffett"),
    "direct_answer": ("结论", "答案", "怎么看", "是否", "direct", "answer"),
}

_OPERATION_DIMENSIONS: dict[str, tuple[str, ...]] = {
    "generate_report": ("direct_answer", "fundamental", "valuation", "risk", "catalyst"),
    "investment_opinion": ("direct_answer", "price", "technical", "news", "fundamental", "valuation", "risk"),
    "earnings_impact": ("direct_answer", "price", "news", "fundamental", "risk", "catalyst"),
    "earnings_performance": ("direct_answer", "fundamental", "news", "risk"),
    "daily_brief": ("direct_answer", "price", "news", "risk"),
    "analyze_impact": ("direct_answer", "catalyst", "risk"),
    "technical": ("technical",),
    "fundamental": ("fundamental", "valuation"),
    "price": ("price",),
    "fetch": ("news",),
    "news_impact": ("news", "catalyst", "risk"),
    "compare": ("direct_answer", "valuation", "risk"),
    "holdings": ("holdings", "portfolio"),
}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _text_contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(token.lower() in lowered for token in tokens)


def _target(target_id: str, *, label: str | None = None, source: str = "deterministic") -> dict[str, Any]:
    label_text = label or {
        "valuation": "估值",
        "risk": "风险",
        "catalyst": "催化剂/未来关注",
        "technical": "技术面",
        "fundamental": "基本面",
        "macro": "宏观",
        "price": "价格",
        "news": "新闻",
        "portfolio": "组合",
        "holdings": "持仓披露",
        "direct_answer": "直接回答",
    }.get(target_id, target_id)
    return {"target_id": target_id, "label": label_text, "source": source}


def _dedupe_targets(targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in targets:
        target_id = _clean(item.get("target_id") or item.get("id")).lower()
        if not target_id:
            continue
        if target_id in seen:
            if item.get("source") == "continuation_target":
                for idx, existing in enumerate(result):
                    if existing.get("target_id") == target_id:
                        result[idx] = {**existing, **item, "target_id": target_id}
                        break
            continue
        seen.add(target_id)
        normalized = dict(item)
        normalized["target_id"] = target_id
        normalized.setdefault("label", target_id)
        result.append(normalized)
    return result


def _operation_name(task: dict[str, Any]) -> str:
    operation = task.get("operation")
    if isinstance(operation, dict):
        return _clean(operation.get("name")).lower()
    return _clean(task.get("operation")).lower()


def build_answer_targets(state: dict[str, Any]) -> list[dict[str, Any]]:
    query = _clean(state.get("query"))
    targets: list[dict[str, Any]] = []

    tasks = state.get("tasks")
    if isinstance(tasks, list):
        for task in tasks:
            if not isinstance(task, dict):
                continue
            op_name = _operation_name(task)
            for dimension in _OPERATION_DIMENSIONS.get(op_name, ()):
                targets.append(_target(dimension, source=f"task:{op_name}"))

    op = state.get("operation")
    if isinstance(op, dict):
        for dimension in _OPERATION_DIMENSIONS.get(_clean(op.get("name")).lower(), ()):
            targets.append(_target(dimension, source="operation"))

    for dimension, keywords in _DIMENSION_KEYWORDS.items():
        if _text_contains_any(query, keywords):
            targets.append(_target(dimension, source="query"))

    reply_contract = state.get("reply_contract")
    if isinstance(reply_contract, dict) and isinstance(reply_contract.get("continuation_target"), dict):
        target = reply_contract["continuation_target"]
        label = _clean(target.get("label") or target.get("question") or target.get("title"))
        targets.append(_target("direct_answer", label=label or None, source="continuation_target"))

    if not targets:
        targets.append(_target("direct_answer", source="fallback"))
    return _dedupe_targets(targets)


def _claims_from_ledger(ledger: Any) -> list[dict[str, Any]]:
    if isinstance(ledger, BaseModel):
        payload = ledger.model_dump(mode="json")
    elif isinstance(ledger, dict):
        payload = ledger
    else:
        payload = {}
    claims = payload.get("claims") if isinstance(payload, dict) else []
    if not isinstance(claims, list):
        return []
    return [claim for claim in claims if isinstance(claim, dict)]


def evaluate_coverage(ledger: Any, targets: list[dict[str, Any]]) -> dict[str, Any]:
    normalized_targets = _dedupe_targets(targets)
    claims = _claims_from_ledger(ledger)
    claim_texts = [
        " ".join(
            [
                _clean(claim.get("claim")),
                _clean(claim.get("stance")),
                " ".join(_clean(item) for item in claim.get("limitations", []) if _clean(item))
                if isinstance(claim.get("limitations"), list)
                else "",
            ]
        )
        for claim in claims
    ]
    corpus = "\n".join(claim_texts)

    answered: list[dict[str, Any]] = []
    unanswered: list[dict[str, Any]] = []
    for target in normalized_targets:
        target_id = _clean(target.get("target_id")).lower()
        keywords = _DIMENSION_KEYWORDS.get(target_id, (target_id,))
        covered = bool(corpus and _text_contains_any(corpus, keywords))
        row = {**target, "covered": covered}
        if covered:
            row["matched_claim_count"] = sum(1 for text in claim_texts if _text_contains_any(text, keywords))
            answered.append(row)
        else:
            unanswered.append(row)

    total = len(normalized_targets)
    coverage_rate = len(answered) / total if total else 1.0
    return {
        "targets": normalized_targets,
        "answered_targets": answered,
        "unanswered_targets": unanswered,
        "coverage_rate": round(coverage_rate, 4),
        "claim_count": len(claims),
    }


def coverage_warning_text(coverage: dict[str, Any]) -> str:
    unanswered = coverage.get("unanswered_targets") if isinstance(coverage, dict) else []
    if not isinstance(unanswered, list) or not unanswered:
        return ""
    labels = [_clean(item.get("label") if isinstance(item, dict) else item) for item in unanswered]
    labels = [label for label in labels if label]
    return "以下问题尚未被证据账本充分覆盖：" + "、".join(labels[:6])


__all__ = ["build_answer_targets", "evaluate_coverage", "coverage_warning_text"]
