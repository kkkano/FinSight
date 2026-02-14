# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class AgentCapability:
    name: str
    subject_weights: dict[str, float]
    operation_weights: dict[str, float]
    output_mode_weights: dict[str, float]
    keyword_hints: tuple[str, ...] = ()
    keyword_boost: float = 0.25


REPORT_AGENT_CANDIDATES: tuple[str, ...] = (
    "price_agent",
    "news_agent",
    "fundamental_agent",
    "technical_agent",
    "macro_agent",
    "deep_search_agent",
)


AGENT_CAPABILITIES: dict[str, AgentCapability] = {
    "price_agent": AgentCapability(
        name="price_agent",
        subject_weights={"company": 0.55, "portfolio": 0.4, "news_item": 0.2, "news_set": 0.2},
        operation_weights={"price": 0.65, "technical": 0.35, "compare": 0.45, "generate_report": 0.3},
        output_mode_weights={"investment_report": 0.3, "brief": 0.1, "chat": 0.05},
        keyword_hints=("\u80a1\u4ef7", "\u4ef7\u683c", "price", "\u884c\u60c5", "quote"),
    ),
    "news_agent": AgentCapability(
        name="news_agent",
        subject_weights={"news_item": 0.7, "news_set": 0.75, "company": 0.45, "portfolio": 0.2},
        operation_weights={"fetch": 0.65, "analyze_impact": 0.45, "summarize": 0.4, "generate_report": 0.3},
        output_mode_weights={"investment_report": 0.25, "brief": 0.1, "chat": 0.05},
        keyword_hints=("\u65b0\u95fb", "news", "headline", "\u5feb\u8baf", "\u4e8b\u4ef6"),
    ),
    "fundamental_agent": AgentCapability(
        name="fundamental_agent",
        subject_weights={"company": 0.6, "filing": 0.6, "research_doc": 0.45, "portfolio": 0.25},
        operation_weights={"generate_report": 0.55, "compare": 0.45, "analyze_impact": 0.25, "summarize": 0.2},
        output_mode_weights={"investment_report": 0.35, "brief": 0.05},
        keyword_hints=("\u57fa\u672c\u9762", "fundamental", "\u8d22\u52a1", "\u4f30\u503c", "valuation"),
    ),
    "technical_agent": AgentCapability(
        name="technical_agent",
        subject_weights={"company": 0.5, "portfolio": 0.35},
        operation_weights={"technical": 0.75, "price": 0.2, "compare": 0.15, "generate_report": 0.15},
        output_mode_weights={"investment_report": 0.2, "brief": 0.1},
        keyword_hints=("\u6280\u672f\u9762", "technical", "rsi", "macd", "\u5747\u7ebf", "ma"),
    ),
    "macro_agent": AgentCapability(
        name="macro_agent",
        subject_weights={"company": 0.35, "portfolio": 0.45, "news_set": 0.35},
        operation_weights={"generate_report": 0.35, "analyze_impact": 0.35, "compare": 0.2},
        output_mode_weights={"investment_report": 0.25, "brief": 0.05},
        keyword_hints=("\u5b8f\u89c2", "macro", "cpi", "ppi", "fed", "fomc", "\u5229\u7387", "\u901a\u80c0", "\u5c31\u4e1a"),
    ),
    "deep_search_agent": AgentCapability(
        name="deep_search_agent",
        subject_weights={"research_doc": 0.85, "filing": 0.85, "company": 0.1, "news_set": 0.1},
        operation_weights={"generate_report": 0.15, "qa": 0.2, "analyze_impact": 0.1, "compare": 0.1},
        output_mode_weights={"investment_report": 0.1, "brief": 0.05},
        keyword_hints=("\u6df1\u5ea6", "deep", "\u7814\u62a5", "filing", "document", "\u8c03\u7814"),
        keyword_boost=0.45,
    ),
}


_MACRO_HINTS = ("\u5b8f\u89c2", "macro", "cpi", "ppi", "fed", "fomc", "\u5229\u7387", "\u901a\u80c0", "\u5c31\u4e1a", "gdp")
_TECHNICAL_HINTS = ("\u6280\u672f", "technical", "rsi", "macd", "\u5747\u7ebf", "k\u7ebf", "ma")
_DEEP_HINTS = ("\u6df1\u5ea6", "deep", "\u8c03\u7814", "\u7814\u62a5", "filing", "document", "\u6587\u6863")


def _subject_type(state: dict[str, Any]) -> str:
    subject = state.get("subject") if isinstance(state, dict) else {}
    subject = subject if isinstance(subject, dict) else {}
    subject_type = subject.get("subject_type")
    return str(subject_type).strip() if isinstance(subject_type, str) and subject_type.strip() else "unknown"


def _operation_name(state: dict[str, Any]) -> str:
    operation = state.get("operation") if isinstance(state, dict) else {}
    operation = operation if isinstance(operation, dict) else {}
    op_name = operation.get("name")
    return str(op_name).strip() if isinstance(op_name, str) and op_name.strip() else "qa"


def _query_text(state: dict[str, Any]) -> str:
    query = state.get("query") if isinstance(state, dict) else ""
    return str(query).lower() if isinstance(query, str) else ""


def _selection_types(state: dict[str, Any]) -> set[str]:
    subject = state.get("subject") if isinstance(state, dict) else {}
    subject = subject if isinstance(subject, dict) else {}
    raw = subject.get("selection_types")
    if not isinstance(raw, list):
        return set()
    return {str(x).strip().lower() for x in raw if isinstance(x, str) and str(x).strip()}


def _contains_any(query: str, hints: Iterable[str]) -> bool:
    return any(h in query for h in hints if h)


def score_agent_for_request(agent_name: str, state: dict[str, Any]) -> tuple[float, list[str]]:
    spec = AGENT_CAPABILITIES.get(agent_name)
    if not spec:
        return 0.0, ["not registered"]

    subject_type = _subject_type(state)
    operation = _operation_name(state)
    output_mode = str(state.get("output_mode") or "brief")
    query = _query_text(state)
    selection_types = _selection_types(state)

    score = 0.05
    reasons: list[str] = ["base=0.05"]

    subject_score = spec.subject_weights.get(subject_type, 0.0)
    if subject_score > 0:
        score += subject_score
        reasons.append(f"subject:{subject_type}=+{subject_score:.2f}")

    operation_score = spec.operation_weights.get(operation, 0.0)
    if operation_score > 0:
        score += operation_score
        reasons.append(f"operation:{operation}=+{operation_score:.2f}")

    output_score = spec.output_mode_weights.get(output_mode, 0.0)
    if output_score > 0:
        score += output_score
        reasons.append(f"output:{output_mode}=+{output_score:.2f}")

    if query and _contains_any(query, spec.keyword_hints):
        score += spec.keyword_boost
        reasons.append(f"keyword:+{spec.keyword_boost:.2f}")

    if agent_name == "news_agent" and "news" in selection_types:
        score += 0.2
        reasons.append("selection:news=+0.20")
    if agent_name == "deep_search_agent" and subject_type in ("filing", "research_doc"):
        score += 0.35
        reasons.append("subject:doc_or_filing=+0.35")

    return round(score, 4), reasons


def required_agents_for_request(state: dict[str, Any], candidates: Iterable[str]) -> list[str]:
    output_mode = str(state.get("output_mode") or "brief")
    if output_mode != "investment_report":
        return []

    candidate_set = {str(x).strip() for x in candidates if isinstance(x, str) and str(x).strip()}
    subject_type = _subject_type(state)
    operation = _operation_name(state)
    query = _query_text(state)

    required: list[str]
    if operation == "technical":
        required = ["price_agent", "technical_agent"]
    elif operation == "price":
        required = ["price_agent"]
    elif operation == "compare":
        required = ["price_agent", "fundamental_agent"]
    elif subject_type in ("filing", "research_doc"):
        required = ["deep_search_agent", "fundamental_agent"]
    elif subject_type in ("news_item", "news_set"):
        required = ["news_agent", "price_agent"]
    elif subject_type == "company":
        required = ["price_agent", "news_agent", "fundamental_agent"]
        # Always include macro + technical for comprehensive investment reports
        if output_mode == "investment_report":
            required.extend(["macro_agent", "technical_agent"])
    else:
        required = ["price_agent", "news_agent"]

    if query and _contains_any(query, _MACRO_HINTS):
        required.append("macro_agent")
    if query and _contains_any(query, _TECHNICAL_HINTS):
        required.extend(["price_agent", "technical_agent"])
    if query and _contains_any(query, _DEEP_HINTS):
        required.append("deep_search_agent")

    deduped: list[str] = []
    seen: set[str] = set()
    for name in required:
        if name not in candidate_set:
            continue
        if name in seen:
            continue
        deduped.append(name)
        seen.add(name)
    return deduped


def select_agents_for_request(
    state: dict[str, Any],
    candidates: Iterable[str],
    *,
    max_agents: int = 4,
    min_agents: int = 2,
) -> dict[str, Any]:
    unique_candidates: list[str] = []
    seen: set[str] = set()
    for raw in candidates:
        name = str(raw).strip() if isinstance(raw, str) else ""
        if not name or name in seen:
            continue
        unique_candidates.append(name)
        seen.add(name)

    if not unique_candidates or max_agents <= 0:
        return {"selected": [], "scores": {}, "reasons": {}, "required": []}

    scored: list[dict[str, Any]] = []
    for name in unique_candidates:
        score, reasons = score_agent_for_request(name, state)
        scored.append({"name": name, "score": score, "reasons": reasons})
    scored.sort(key=lambda x: (-float(x["score"]), str(x["name"])))

    rank_pos = {str(item["name"]): idx for idx, item in enumerate(scored)}
    required = required_agents_for_request(state, unique_candidates)
    required = sorted(required, key=lambda name: rank_pos.get(name, 10_000))

    target = min(max_agents, len(unique_candidates))
    if max_agents >= min_agents:
        target = max(target, min(min_agents, len(unique_candidates)))
    if required:
        target = max(target, min(len(unique_candidates), len(required)))
    target = max(1, target)

    selected: list[str] = []
    for name in required:
        if len(selected) >= target:
            break
        if name not in selected:
            selected.append(name)

    for item in scored:
        if len(selected) >= target:
            break
        name = str(item["name"])
        if name not in selected:
            selected.append(name)

    scores = {str(item["name"]): float(item["score"]) for item in scored}
    reasons = {str(item["name"]): list(item["reasons"]) for item in scored}
    return {"selected": selected, "scores": scores, "reasons": reasons, "required": required}


__all__ = [
    "AGENT_CAPABILITIES",
    "REPORT_AGENT_CANDIDATES",
    "required_agents_for_request",
    "score_agent_for_request",
    "select_agents_for_request",
]
