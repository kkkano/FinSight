# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

from backend.research.evidence_ledger import EvidenceLedger, ResearchClaim


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _as_ledger(value: Any) -> EvidenceLedger:
    if isinstance(value, EvidenceLedger):
        return value
    if isinstance(value, dict):
        return EvidenceLedger.model_validate(value)
    raise TypeError("evidence ledger must be a dict or EvidenceLedger")


def _source_reliability_by_id(ledger: EvidenceLedger) -> dict[str, float]:
    return {source.source_id: float(source.reliability) for source in ledger.sources}


def _claim_source_reliability(claim: ResearchClaim, reliabilities: dict[str, float]) -> float:
    scores = [reliabilities[source_id] for source_id in claim.evidence_ids if source_id in reliabilities]
    if not scores:
        return 0.5
    return _clamp(sum(scores) / len(scores))


def _claim_weight(claim: ResearchClaim, reliabilities: dict[str, float]) -> float:
    return _clamp((float(claim.confidence) * 0.65) + (_claim_source_reliability(claim, reliabilities) * 0.35))


def _serialise_claim(claim: ResearchClaim, reliabilities: dict[str, float]) -> dict[str, Any]:
    return {
        "claim_id": claim.claim_id,
        "claim": claim.claim,
        "stance": claim.stance,
        "evidence_ids": list(claim.evidence_ids),
        "confidence": float(claim.confidence),
        "agent_name": claim.agent_name,
        "limitations": list(claim.limitations),
        "weight": round(_claim_weight(claim, reliabilities), 4),
    }


def _claims_for_stances(ledger: EvidenceLedger, stances: set[str]) -> list[ResearchClaim]:
    return sorted(
        [claim for claim in ledger.claims if str(claim.stance).lower() in stances],
        key=lambda claim: (float(claim.confidence), len(claim.evidence_ids)),
        reverse=True,
    )


def _build_thesis(ledger: EvidenceLedger, *, stances: set[str], label: str) -> dict[str, Any]:
    reliabilities = _source_reliability_by_id(ledger)
    claims = _claims_for_stances(ledger, stances)
    serialised = [_serialise_claim(claim, reliabilities) for claim in claims]
    weights = [float(item["weight"]) for item in serialised]
    average_confidence = sum(float(claim.confidence) for claim in claims) / len(claims) if claims else 0.0
    evidence_weight = sum(weights) / len(weights) if weights else 0.0
    return {
        "stance": label,
        "claim_count": len(serialised),
        "claims": serialised,
        "average_confidence": round(_clamp(average_confidence), 4),
        "evidence_weight": round(_clamp(evidence_weight), 4),
    }


def build_bull_thesis(ledger: Any) -> dict[str, Any]:
    """构建看多论点集合。"""
    parsed = _as_ledger(ledger)
    return _build_thesis(parsed, stances={"bull"}, label="bull")


def build_bear_thesis(ledger: Any) -> dict[str, Any]:
    """构建看空/风险论点集合。"""
    parsed = _as_ledger(ledger)
    return _build_thesis(parsed, stances={"bear", "risk"}, label="bear")


def cross_examine(bull: dict[str, Any], bear: dict[str, Any]) -> list[dict[str, Any]]:
    """用确定性方式把多空核心 claim 配对，供报告层解释分歧。"""
    bull_claims = bull.get("claims") if isinstance(bull.get("claims"), list) else []
    bear_claims = bear.get("claims") if isinstance(bear.get("claims"), list) else []
    if not bull_claims or not bear_claims:
        return []

    rounds: list[dict[str, Any]] = []
    for index, (bull_claim, bear_claim) in enumerate(zip(bull_claims[:4], bear_claims[:4]), start=1):
        rounds.append(
            {
                "round": index,
                "bull_claim_id": bull_claim.get("claim_id"),
                "bear_claim_id": bear_claim.get("claim_id"),
                "question": "该看多论点是否已经充分抵消对应的估值、政策或下行风险？",
                "bull_claim": bull_claim.get("claim", ""),
                "bear_challenge": bear_claim.get("claim", ""),
                "evidence_gap": "需要补充直接证据来判断哪一侧更能解释未来收益风险比。",
            }
        )
    return rounds


def judge_debate(
    ledger: Any,
    bull: dict[str, Any],
    bear: dict[str, Any],
) -> dict[str, Any]:
    parsed = _as_ledger(ledger)
    bull_score = _clamp(float(bull.get("evidence_weight") or 0.0))
    bear_score = _clamp(float(bear.get("evidence_weight") or 0.0))
    if bull.get("claim_count", 0) == 0 and bear.get("claim_count", 0) == 0:
        evidence_balance = "insufficient"
    elif abs(bull_score - bear_score) < 0.08:
        evidence_balance = "mixed"
    else:
        evidence_balance = "bull" if bull_score > bear_score else "bear"

    disagreements: list[str] = []
    for item in parsed.contradictions[:4]:
        if isinstance(item, dict):
            reason = str(item.get("reason") or item.get("claim") or item).strip()
        else:
            reason = str(item or "").strip()
        if reason:
            disagreements.append(reason)
    if not disagreements and bull.get("claims") and bear.get("claims"):
        disagreements.append("看多增长/需求论点与看空估值/风险论点需要进一步交叉验证。")

    return {
        "bull_score": round(bull_score, 4),
        "bear_score": round(bear_score, 4),
        "evidence_balance": evidence_balance,
        "key_disagreements": disagreements,
        "source_count": len(parsed.sources),
        "claim_count": len(parsed.claims),
    }


def _claim_agents(claims: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for claim in claims:
        agent = str(claim.get("agent_name") or "").strip()
        if not agent or agent in seen:
            continue
        seen.add(agent)
        result.append(agent)
    return result


def build_read_only_adjudications(
    *,
    cross_examination: list[dict[str, Any]],
    bull: dict[str, Any],
    bear: dict[str, Any],
    scorecard: dict[str, Any],
) -> list[dict[str, Any]]:
    balance = str(scorecard.get("evidence_balance") or "insufficient").strip() or "insufficient"
    bull_claims = bull.get("claims") if isinstance(bull.get("claims"), list) else []
    bear_claims = bear.get("claims") if isinstance(bear.get("claims"), list) else []
    supporting_agents = _claim_agents(bull_claims)
    opposing_agents = _claim_agents(bear_claims)
    disagreements = scorecard.get("key_disagreements") if isinstance(scorecard.get("key_disagreements"), list) else []
    rows: list[dict[str, Any]] = []

    if cross_examination:
        for item in cross_examination[:4]:
            topic = str(item.get("question") or "Cross-agent disagreement").strip()
            rationale = str(item.get("evidence_gap") or "").strip()
            if not rationale:
                rationale = "Bull and bear claims need source-level review before the system adopts one side."
            rows.append(
                {
                    "topic": topic,
                    "supporting_agents": supporting_agents,
                    "opposing_agents": opposing_agents,
                    "adjudication": balance,
                    "rationale": rationale,
                    "bull_claim_id": item.get("bull_claim_id"),
                    "bear_claim_id": item.get("bear_claim_id"),
                }
            )
        return rows

    for index, disagreement in enumerate(disagreements[:4], start=1):
        rows.append(
            {
                "topic": f"Disagreement {index}",
                "supporting_agents": supporting_agents,
                "opposing_agents": opposing_agents,
                "adjudication": balance,
                "rationale": str(disagreement),
            }
        )
    return rows


def build_debate_artifact(ledger: Any, query: str = "") -> dict[str, Any]:
    parsed = _as_ledger(ledger)
    bull = build_bull_thesis(parsed)
    bear = build_bear_thesis(parsed)
    cross = cross_examine(bull, bear)
    scorecard = judge_debate(parsed, bull, bear)
    adjudications = build_read_only_adjudications(
        cross_examination=cross,
        bull=bull,
        bear=bear,
        scorecard=scorecard,
    )
    balance = scorecard.get("evidence_balance")
    if balance == "bull":
        consensus = "当前证据略偏看多，但需持续验证主要风险是否缓解。"
    elif balance == "bear":
        consensus = "当前证据略偏谨慎，风险与估值压力对结论约束更强。"
    elif balance == "insufficient":
        consensus = "当前证据不足，无法形成稳定的多空判断。"
    else:
        consensus = "当前证据呈混合状态，应同时跟踪看多驱动和看空风险的变化。"

    open_questions = list(parsed.uncertainties[:6])
    if cross:
        open_questions.append("多空核心分歧需要补充高可靠来源或最新披露来裁决。")
    if not open_questions:
        open_questions.append("后续需要补充更多来源来验证结论稳定性。")

    return {
        "enabled": True,
        "status": "done",
        "query": query or parsed.query,
        "ledger_id": parsed.ledger_id,
        "bull_score": scorecard.get("bull_score", 0.0),
        "bear_score": scorecard.get("bear_score", 0.0),
        "judge_score": round((float(scorecard.get("bull_score") or 0.0) + float(scorecard.get("bear_score") or 0.0)) / 2, 4),
        "winner": {"bull": "bull", "bear": "bear", "mixed": "balanced", "insufficient": "unknown"}.get(str(balance), "unknown"),
        "key_disagreements": list(scorecard.get("key_disagreements") or []),
        "bull_thesis": bull,
        "bear_thesis": bear,
        "cross_examination": cross,
        "adjudications": adjudications,
        "judge_scorecard": scorecard,
        "consensus": consensus,
        "open_questions": open_questions,
    }


__all__ = [
    "build_bear_thesis",
    "build_bull_thesis",
    "build_debate_artifact",
    "cross_examine",
    "build_read_only_adjudications",
    "judge_debate",
]
