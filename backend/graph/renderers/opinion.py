# -*- coding: utf-8 -*-
"""投资观点 renderer：仅消费 OpinionReadiness 结构化产物。"""
from __future__ import annotations

from typing import Any

from backend.graph.state import GraphState
from backend.graph.synthesis.contracts import Claim, NormalizedEvidence, TaskSynthesisResult
from backend.graph.synthesis.opinion_readiness import OpinionReadiness

_DIRECTION_LABEL = {"bull": "偏多", "bear": "偏空", "neutral": "中性"}
_REASON_LABEL = {
    "missing_symbol": "缺少唯一分析标的",
    "missing_price_anchor": "缺少带时间的有效价格锚点",
    "missing_core_evidence": "缺少技术、基本面、估值或盈利核心证据",
    "insufficient_independent_dimensions": "独立证据维度不足",
    "unsupported_direction": "方向提案缺少有效 Claim 支持",
    "unresolved_material_conflict": "存在未解决的重大方向冲突",
    "evidence_contract_invalid": "证据合同未通过一致性校验",
}


def _artifact_slice(state: GraphState) -> tuple[TaskSynthesisResult, OpinionReadiness, dict[str, Claim], dict[str, NormalizedEvidence]] | None:
    artifacts = state.get("artifacts") if isinstance(state.get("artifacts"), dict) else {}
    raw = artifacts.get("opinion_synthesis") if isinstance(artifacts.get("opinion_synthesis"), dict) else {}
    tasks = state.get("tasks") if isinstance(state.get("tasks"), list) else []
    task_id = str((tasks[0] if tasks and isinstance(tasks[0], dict) else {}).get("id") or "")
    raw_results = raw.get("task_results_by_task") if isinstance(raw.get("task_results_by_task"), dict) else {}
    raw_readiness = raw.get("readiness_by_task") if isinstance(raw.get("readiness_by_task"), dict) else {}
    claims_payload = (raw.get("claim_validation") or {}).get("valid_claims") if isinstance(raw.get("claim_validation"), dict) else {}
    evidence_payload = (raw.get("evidence_normalization") or {}).get("evidence_index") if isinstance(raw.get("evidence_normalization"), dict) else {}
    if not task_id or task_id not in raw_results or task_id not in raw_readiness:
        return None
    return (
        TaskSynthesisResult.model_validate(raw_results[task_id]),
        OpinionReadiness.model_validate(raw_readiness[task_id]),
        {key: Claim.model_validate(value) for key, value in (claims_payload or {}).items()},
        {key: NormalizedEvidence.model_validate(value) for key, value in (evidence_payload or {}).items()},
    )


def render_investment_opinion(state: GraphState, ctx: dict[str, Any]) -> str | None:
    if "investment_opinion" not in ctx["operations"]:
        return None
    payload = _artifact_slice(state)
    if payload is None:
        return "**证据状态：暂不能形成方向判断**\n\n- 结构化证据尚未就绪。\n"
    result, readiness, claims, evidence = payload
    lines: list[str] = []
    if not readiness.direction_allowed:
        lines.append("**证据状态：暂不能形成方向判断**")
        lines.append("")
        for code in readiness.reason_codes:
            lines.append(f"- {_REASON_LABEL[code]}")
    else:
        lines.append(f"**方向判断：{_DIRECTION_LABEL[readiness.proposed_direction]}**")
        lines.append("")
        anchor = evidence[readiness.price_anchor_source_id]
        lines.append(f"- 价格锚点：{anchor.market_price:g}（{anchor.as_of}，[{anchor.source_id}]）")
        for claim_id in readiness.supporting_claim_ids:
            claim = claims[claim_id]
            refs = " ".join(f"[{item}]" for item in claim.evidence_ids)
            lines.append(f"- {claim.text} {refs}".rstrip())
    if readiness.qualified_dimensions:
        lines.extend(["", "**已验证维度**"])
        lines.extend(f"- {item}" for item in readiness.qualified_dimensions)
    limitations = list(result.limitations)
    if limitations:
        lines.extend(["", "**限制**"])
        lines.extend(f"- {item}" for item in dict.fromkeys(limitations))
    return "\n".join(lines).strip() + "\n"


__all__ = ["render_investment_opinion"]
