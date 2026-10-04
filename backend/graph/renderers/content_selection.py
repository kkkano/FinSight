# -*- coding: utf-8 -*-
"""正文选择只消费研究合同；完整证据和论据仍留在研究结果中。"""
from __future__ import annotations

from backend.graph.renderers.fact_formatters import payload_for


DIMENSION_KINDS = {
    "fundamental_quality": {"fundamental_snapshot", "filing_context"},
    "valuation_reasonableness": {"company_profile", "earnings_estimates"},
    "business_model": {"company_profile", "filing_context", "document_context"},
    "competition": {"company_profile", "news_context", "document_context"},
    "risk_level": {"risk_profile", "options_derivatives"},
    "earnings_impact": {"filing_context", "fundamental_snapshot", "earnings_estimates"},
    "trend_quality": {"technical_snapshot", "price_snapshot"},
    "technical_quality": {"technical_snapshot"},
    "news_catalysts": {"event_calendar", "news_context"},
    "external_impact": {"macro_context", "news_context"},
    "performance": {"performance_comparison", "price_snapshot"},
}


def select_fact_ids(draft, task, profile: str) -> list[str]:
    if profile == "full":
        return list(task.fact_ids)
    facts = [draft.evidence_index[source_id] for source_id in task.fact_ids if source_id in draft.evidence_index and draft.evidence_index[source_id].usage == "fact"]
    preferred = [*task.selected_fact_ids, *[source_id for claim_id in task.claim_ids if claim_id in draft.claim_index and draft.claim_index[claim_id].agent_name == "research_analyst" for source_id in draft.claim_index[claim_id].evidence_ids]]
    wanted = set()
    for dimension in task.requested_dimensions:
        wanted.update(DIMENSION_KINDS.get(dimension, set()))
    for requirement in task.answer_requirements:
        wanted.update(requirement.get("evidence_kinds") or [])
    if not wanted:
        wanted = {item.kind for item in facts}
    if task.operation in {"price", "investment_opinion", "technical"}:
        wanted.add("price_snapshot")
    if task.operation == "macro_brief":
        wanted.update({"macro_context", "event_calendar"})
    wanted.update(item.kind for item in facts if item.source_id in preferred)

    def rank(item):
        payload = payload_for(item)
        selected = item.source_id in preferred
        priority = preferred.index(item.source_id) if selected else len(preferred)
        complete = bool(payload.get("fact_metadata") or payload.get("rsi14") is not None or payload.get("factor_beta") or payload.get("earnings_estimate"))
        return (not selected, priority, not complete, -(int((item.period_end or item.as_of or "0000")[:4]) if (item.period_end or item.as_of or "")[:4].isdigit() else 0))

    chronological = sorted(facts, key=lambda item: item.period_end or item.as_of or "", reverse=True)
    ordered = sorted(chronological, key=rank)
    groups = {}
    for item in ordered:
        if item.kind not in wanted:
            continue
        group = "financial" if item.kind in {"filing_context", "fundamental_snapshot"} else item.kind
        groups.setdefault((item.subject, group), []).append(item)
    selected_ids = []
    for (_subject, kind), items in groups.items():
        if kind == "financial":
            structured = next((item for item in items if payload_for(item).get("fact_metadata") or isinstance(payload_for(item).get("revenue"), list)), None)
            if structured is not None:
                selected = [structured]
            else:
                selected = []
                for metric in ("revenue", "net_income", "operating_cash_flow"):
                    item = next((item for item in items if item.metric == metric or item.metadata.get("metric_key") == metric), None)
                    if item is not None:
                        selected.append(item)
                if not selected:
                    selected = items[:1]
        elif kind == "technical_snapshot":
            selected = items[:1]
            if profile != "brief":
                levels = next((item for item in items[1:] if "支撑" in item.text or "阻力" in item.text), None)
                if levels is not None:
                    selected.append(levels)
        elif kind == "macro_context":
            selected = []
            for indicator in ("fed_rate", "cpi", "treasury_10y"):
                item = next((item for item in items if item.metadata.get("indicator_key") == indicator), None)
                if item is not None:
                    selected.append(item)
            if not selected:
                selected = items[:1]
        else:
            limit = 2 if kind == "news_context" and profile == "chat" else 1
            selected = items[:limit]
        selected_ids.extend(item.source_id for item in selected)
    return list(dict.fromkeys(selected_ids))


def select_claims(draft, task, profile: str, *, direction_allowed: bool):
    claims = [draft.claim_index[claim_id] for claim_id in task.claim_ids if claim_id in draft.claim_index and (direction_allowed or not draft.claim_index[claim_id].directional)]
    unique_claims = {}
    for claim in claims:
        unique_claims.setdefault(claim.text, claim)
    claims = list(unique_claims.values())
    if profile == "full":
        return claims
    explanations = [claim for claim in claims if claim.agent_name == "research_analyst"]
    if explanations:
        unique = {}
        for claim in explanations:
            if claim.text.startswith("以下分析仅基于") and "不构成" in claim.text:
                continue
            unique.setdefault(claim.text, claim)
        explanations = list(unique.values())
        result = []
        for dimension in task.requested_dimensions:
            kinds = DIMENSION_KINDS.get(dimension, set())
            matching = [claim for claim in explanations if claim.metric == dimension or any(draft.evidence_index[source_id].kind in kinds for source_id in claim.evidence_ids if source_id in draft.evidence_index)]
            if matching:
                matching.sort(key=lambda claim: claim.metric != dimension)
                if matching[0] not in result:
                    result.append(matching[0])
        if profile == "brief" and result:
            return result[:2]
        return result or explanations[:2 if profile == "brief" else 3]
    result, dimensions = [], set()
    for claim in sorted(claims, key=lambda claim: (claim.metric == "noise_or_secondary_signal", -claim.confidence)):
        if claim.dimension in dimensions:
            continue
        dimensions.add(claim.dimension)
        result.append(claim)
    return result
