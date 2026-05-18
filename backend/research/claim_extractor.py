# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from backend.research.evidence_ledger import stable_id


VALID_STANCES = {"bull", "bear", "neutral", "risk", "unknown"}

BULLISH_TERMS = (
    "bull",
    "bullish",
    "upside",
    "growth",
    "accelerat",
    "expansion",
    "beat",
    "strong",
    "resilient",
    "improv",
    "positive",
    "outperform",
    "upgrade",
    "buy",
    "tailwind",
    "momentum",
    "rally",
    "增长",
    "上行",
    "上涨",
    "利好",
    "强劲",
    "改善",
    "超预期",
    "好于预期",
    "上调",
    "看多",
    "多头",
    "买入",
    "反弹",
)

BEARISH_TERMS = (
    "bear",
    "bearish",
    "downside",
    "declin",
    "fall",
    "weak",
    "deteriorat",
    "contraction",
    "decelerat",
    "loss",
    "negative",
    "miss",
    "below",
    "downgrade",
    "sell-off",
    "pressure",
    "headwind",
    "下行",
    "下跌",
    "下降",
    "下滑",
    "承压",
    "疲弱",
    "弱于",
    "亏损",
    "负面",
    "低于预期",
    "下调",
    "看空",
    "空头",
)

RISK_TERMS = (
    "risk",
    "uncertain",
    "volatility",
    "volatile",
    "drawdown",
    "litigation",
    "regulatory",
    "bankruptcy",
    "impairment",
    "exposure",
    "stress",
    "风险",
    "不确定",
    "波动",
    "回撤",
    "诉讼",
    "监管",
    "破产",
    "减值",
    "敞口",
    "压力",
)

NEUTRAL_TERMS = (
    "neutral",
    "mixed",
    "balanced",
    "stable",
    "range-bound",
    "中性",
    "分化",
    "均衡",
    "稳定",
    "震荡",
)


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if is_dataclass(value):
        try:
            payload = asdict(value)
            return dict(payload) if isinstance(payload, dict) else {}
        except Exception:
            return {}
    return {}


def _list_of_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        cleaned = value.strip()
        return [cleaned] if cleaned else []
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result


def _clamp_confidence(value: Any, default: float = 0.5) -> float:
    try:
        result = float(value)
    except Exception:
        result = default
    return max(0.0, min(1.0, result))


def _count_terms(text: str, terms: tuple[str, ...]) -> int:
    lowered = text.lower()
    return sum(1 for term in terms if term in lowered)


def _evidence_ids(output: dict[str, Any]) -> list[str]:
    evidence = output.get("evidence")
    if not isinstance(evidence, list):
        return []

    ids: list[str] = []
    for item in evidence:
        payload = _as_dict(item)
        meta = _as_dict(payload.get("meta"))
        explicit_id = (
            _clean_text(payload.get("source_id"))
            or _clean_text(payload.get("id"))
            or _clean_text(meta.get("source_id"))
            or _clean_text(meta.get("id"))
        )
        if explicit_id:
            ids.append(explicit_id)
    return _dedupe_strings(ids)


def infer_stance(text: str, risks: list[str]) -> str:
    cleaned_text = _clean_text(text)
    risk_text = "\n".join(_list_of_strings(risks))
    combined = f"{cleaned_text}\n{risk_text}"

    bull_score = _count_terms(cleaned_text, BULLISH_TERMS)
    bear_score = _count_terms(cleaned_text, BEARISH_TERMS)
    risk_score = _count_terms(combined, RISK_TERMS)
    neutral_score = _count_terms(cleaned_text, NEUTRAL_TERMS)

    if risk_score and risk_score >= bull_score and risk_score >= bear_score:
        return "risk"
    if bear_score > bull_score:
        return "bear"
    if bull_score > bear_score:
        return "bull"
    if neutral_score:
        return "neutral"
    if risk_score:
        return "risk"
    return "unknown"


def extract_limitations(output: dict[str, Any]) -> list[str]:
    quality = _as_dict(output.get("evidence_quality"))
    limitations = (
        _list_of_strings(output.get("limitations"))
        + _list_of_strings(output.get("risks"))
        + _list_of_strings(output.get("uncertainties"))
        + _list_of_strings(quality.get("limitations"))
        + _list_of_strings(quality.get("uncertainties"))
    )

    if output.get("fallback_used"):
        reason = _clean_text(output.get("fallback_reason"))
        limitations.append(f"fallback_reason={reason or 'unknown'}")

    return _dedupe_strings(limitations)[:12]


def conflicts_to_contradictions(output: dict[str, Any]) -> list[dict[str, Any]]:
    agent_name = _clean_text(output.get("agent_name")) or "unknown_agent"
    raw_conflicts = output.get("conflicting_claims")
    if not isinstance(raw_conflicts, list):
        return []

    contradictions: list[dict[str, Any]] = []
    for item in raw_conflicts:
        if is_dataclass(item):
            try:
                item = asdict(item)
            except Exception:
                item = str(item)

        if isinstance(item, dict):
            contradictions.append(dict(item))
            continue

        cleaned = _clean_text(item)
        if cleaned:
            contradictions.append({"agent_name": agent_name, "claim": cleaned})
    return contradictions


def _normalise_existing_claim(
    payload: dict[str, Any],
    *,
    output: dict[str, Any],
    query: str,
    ticker: str,
    evidence_ids: list[str],
    limitations: list[str],
) -> dict[str, Any] | None:
    claim_text = _clean_text(payload.get("claim") or payload.get("summary") or payload.get("text"))
    if not claim_text:
        return None

    agent_name = _clean_text(payload.get("agent_name")) or _clean_text(output.get("agent_name")) or "unknown_agent"
    risks = _list_of_strings(output.get("risks"))
    stance = _clean_text(payload.get("stance")).lower()
    if stance not in VALID_STANCES:
        stance = infer_stance(claim_text, risks)

    claim_evidence_ids = _dedupe_strings(_list_of_strings(payload.get("evidence_ids"))) or evidence_ids
    claim_limitations = _dedupe_strings(_list_of_strings(payload.get("limitations"))) or limitations

    normalized = dict(payload)
    normalized["claim"] = claim_text[:5000]
    normalized["stance"] = stance
    normalized["evidence_ids"] = claim_evidence_ids
    normalized["confidence"] = _clamp_confidence(payload.get("confidence", output.get("confidence", 0.5)))
    normalized["agent_name"] = agent_name
    normalized["task_ids"] = _dedupe_strings(_list_of_strings(payload.get("task_ids")) or _list_of_strings(output.get("task_ids")))
    normalized["limitations"] = claim_limitations
    normalized["claim_id"] = _clean_text(payload.get("claim_id")) or stable_id(
        "claim",
        agent_name,
        ticker,
        query,
        claim_text,
        claim_evidence_ids,
    )
    return normalized


def extract_claims_from_agent_output(output: dict[str, Any], query: str, ticker: str) -> list[dict[str, Any]]:
    if not isinstance(output, dict):
        return []

    evidence_ids = _evidence_ids(output)
    limitations = extract_limitations(output)
    existing_claims = output.get("claims")
    normalized_claims: list[dict[str, Any]] = []

    if isinstance(existing_claims, list):
        for item in existing_claims:
            payload = _as_dict(item)
            if not payload:
                continue
            claim = _normalise_existing_claim(
                payload,
                output=output,
                query=query,
                ticker=ticker,
                evidence_ids=evidence_ids,
                limitations=limitations,
            )
            if claim is not None:
                normalized_claims.append(claim)

    if normalized_claims:
        return normalized_claims[:12]

    summary = _clean_text(output.get("summary"))
    if not summary:
        return []

    agent_name = _clean_text(output.get("agent_name")) or "unknown_agent"
    risks = _list_of_strings(output.get("risks"))
    claim = {
        "claim_id": stable_id("claim", agent_name, ticker, query, summary, evidence_ids),
        "claim": summary[:5000],
        "stance": infer_stance(summary, risks),
        "evidence_ids": evidence_ids,
        "confidence": _clamp_confidence(output.get("confidence", 0.5)),
        "agent_name": agent_name,
        "task_ids": _dedupe_strings(_list_of_strings(output.get("task_ids"))),
        "limitations": limitations,
    }
    return [claim]
