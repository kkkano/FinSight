# -*- coding: utf-8 -*-
"""深度研究的规范化、校验与结构化合成流水线。"""
from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Callable
from typing import Any, Literal

from langchain_core.messages import HumanMessage
from pydantic import Field

from backend.graph.intent_contract import EvidenceKind
from backend.graph.execution.evidence_tools import evidence_contract_metadata, evidence_is_global
from backend.graph.synthesis.contracts import (
    SCHEMA_VERSION,
    AgentFinding,
    Claim,
    ClaimConflict,
    ClaimValidationResult,
    EvidenceDimension,
    EvidenceNormalizationResult,
    NonEmptyStr,
    NormalizedEvidence,
    RejectedClaim,
    RejectedEvidence,
    ReportSynthesisDraft,
    ReportSynthesisResult,
    StrictContract,
    SynthesisQualityGateResult,
    TaskStatus,
    TaskSynthesisResult,
    aggregate_task_status,
    stable_unique,
)
from backend.graph.synthesis.task_outcomes import TaskDescriptor, TaskOutcome
from backend.services.llm_retry import LLMCallContext, ainvoke_configured_llm, classify_llm_error
from backend.services.llm_response import LLMCompletionError, completion_metadata, final_completion_text
from backend.utils.quote import parse_quote_payload
from backend.utils.env import env_int

_EVIDENCE_KINDS = set(EvidenceKind.__args__)
_STANCE = {"bull", "bear", "neutral", "risk", "unknown"}
_DIMENSIONS = {
    "market", "technical", "fundamental", "valuation", "earnings",
    "catalyst", "risk", "macro", "news", "unknown",
}
_KIND_DIMENSION: dict[str, EvidenceDimension] = {
    "price_snapshot": "market", "performance_comparison": "market",
    "technical_snapshot": "technical", "company_profile": "fundamental",
    "fundamental_snapshot": "fundamental", "filing_context": "fundamental",
    "holdings_ownership": "fundamental", "earnings_estimates": "earnings",
    "transcript_context": "earnings", "event_calendar": "catalyst",
    "risk_profile": "risk", "options_derivatives": "risk",
    "macro_context": "macro", "news_context": "news", "document_context": "unknown",
}
_AGENT_DIMENSION: dict[str, EvidenceDimension] = {
    "price_agent": "market", "technical_agent": "technical",
    "fundamental_agent": "fundamental", "macro_agent": "macro",
    "risk_agent": "risk", "news_agent": "news", "deep_search_agent": "unknown",
}


class _TaskSynthesisSelection(StrictContract):
    """LLM 只能选择已经通过校验的 Claim，不能创建新的事实。"""

    claim_ids: list[NonEmptyStr]
    conclusion_claim_id: NonEmptyStr | None = None
    proposed_direction: Literal["bull", "bear", "neutral"] | None = None
    direction_supporting_claim_ids: list[NonEmptyStr]
    fact_ids: list[NonEmptyStr] = Field(default_factory=list)
    explanation: NonEmptyStr | None = None
    explanation_evidence_ids: list[NonEmptyStr] = Field(default_factory=list)
    explanations: list[dict[str, Any]] = Field(default_factory=list)


class _ReportSynthesisSelection(StrictContract):
    """报告层只生成总括文本并声明其来源 task。"""

    overall_conclusion: NonEmptyStr
    supporting_task_ids: list[NonEmptyStr] = Field(min_length=1)


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None


def _strings(value: Any) -> list[str]:
    if isinstance(value, (str, int, float)):
        value = [value]
    if not isinstance(value, list):
        return []
    return stable_unique([_text(item) for item in value if _text(item)])


def _step_task_ids(step: dict[str, Any]) -> list[str]:
    values = _strings(step.get("task_ids"))
    for item in _strings(step.get("task_id")):
        if item not in values:
            values.append(item)
    return values


def _meta(raw: dict[str, Any]) -> dict[str, Any]:
    return raw.get("meta") if isinstance(raw.get("meta"), dict) else {}


def _kind(raw: dict[str, Any], step: dict[str, Any] | None) -> str:
    meta = _meta(raw)
    for value in (raw.get("kind"), meta.get("evidence_kind"), meta.get("kind")):
        normalized = _text(value)
        if normalized == "unknown":
            return "unknown"
        if normalized in _EVIDENCE_KINDS:
            return normalized
    inputs = step.get("inputs") if isinstance(step, dict) and isinstance(step.get("inputs"), dict) else {}
    required = [item for item in _strings(inputs.get("required_evidence")) if item in _EVIDENCE_KINDS]
    return required[0] if len(required) == 1 else "unknown"


def _display_text(raw: dict[str, Any]) -> str:
    for key in ("text", "snippet", "title"):
        value = _text(raw.get(key))
        if value:
            return value
    structured = raw.get("value", raw.get("data"))
    if structured not in (None, "", [], {}):
        try:
            return json.dumps(structured, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError):
            return ""
    return ""


def clean_research_text(value: Any) -> str:
    """格式头和执行诊断保留在原始产物中，不充当金融事实。"""
    lines = []
    for line in _text(value).splitlines():
        stripped = line.strip()
        if not stripped or re.fullmatch(r"[=\-_*\s]+", stripped):
            continue
        if re.search(r"^(?:\W*综合搜索结果|\W*Search Results|\W*搜索结果\s*[:：])", stripped, re.IGNORECASE):
            continue
        if re.search(r"无\s*ticker.*(?:研究路径|宏观研究)|(?:should|must)\s+(?:route|use).*research", stripped, re.IGNORECASE):
            continue
        if re.search(r"\bquery_coverage\b|\brequest_frame_id\b|\btask_structural_block_reasons\b", stripped):
            continue
        lines.append(stripped)
    return "\n".join(lines)


def _validate_explanation(text: str, sources: list[NormalizedEvidence], claims: list[Claim]) -> None:
    if not clean_research_text(text) or clean_research_text(text) != text.strip():
        raise ValueError("explanation_contains_diagnostics")
    if re.search(r"(?:总体|整体|建议|投资方向).{0,10}(?:偏多|偏空|买入|卖出|持有)|\b(?:bullish|bearish)\b", text, re.IGNORECASE):
        raise ValueError("explanation_contains_unapproved_direction")
    grounding = "\n".join([source.text for source in sources] + [json.dumps(source.structured_data, ensure_ascii=False, default=str) for source in sources] + [claim.text for claim in claims])
    numeric_pattern = re.compile(r"(?<![A-Za-z0-9])([-+]?\d[\d,]*(?:\.\d+)?)(?:[ \t]*(亿|万|[KMBT]|%))?(?![A-Za-z0-9])")
    scales = {"亿": 100_000_000, "万": 10_000, "K": 1000, "M": 1_000_000, "B": 1_000_000_000, "T": 1_000_000_000_000, "%": 0.01}
    available = [float(match.group(1).replace(",", "")) * scales.get(match.group(2), 1) for match in numeric_pattern.finditer(grounding)]
    enumeration_spans = [match.span(1) for match in re.finditer(r"(?m)^\s*(?:[-*]\s*)?(\d+)[.)、](?:\s|[^\d])", text)]
    for match in numeric_pattern.finditer(text):
        if any(start <= match.start(1) < end for start, end in enumeration_spans):
            continue
        token = match.group(1).replace(",", "")
        scale = scales.get(match.group(2), 1)
        requested = float(token) * scale
        places = len(token.split(".", 1)[1]) if "." in token else 0
        tolerance = max(1e-9, 0.5 * 10 ** (-places) * scale)
        if not any(abs(requested - value) <= tolerance for value in available):
            raise ValueError("explanation_contains_unbound_number")
    dates = re.findall(r"\d{4}-\d{2}-\d{2}", text)
    if any(date not in grounding for date in dates):
        raise ValueError("explanation_contains_unbound_date")


def _market_price(raw: dict[str, Any], kind: str) -> float | None:
    if kind != "price_snapshot":
        return None
    meta = _meta(raw)
    for key in ("market_price", "current_price", "price", "close"):
        value = raw.get(key, meta.get(key))
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number) and number > 0:
            return number
    return None


def _agent_output_entries(
    plan_steps: list[dict[str, Any]], agent_outputs: dict[str, Any]
) -> list[tuple[dict[str, Any] | None, dict[str, Any]]]:
    result: list[tuple[dict[str, Any] | None, dict[str, Any]]] = []
    consumed: set[str] = {_text(step.get("id")) for step in plan_steps if _text(step.get("kind")) == "tool"}
    for step in plan_steps:
        if _text(step.get("kind")) != "agent":
            continue
        step_id = _text(step.get("id"))
        output = agent_outputs.get(step_id)
        if isinstance(output, dict) and isinstance(output.get("output"), dict):
            output = output["output"]
        if isinstance(output, dict):
            result.append((step, output))
            consumed.add(step_id)
    for key, output in agent_outputs.items():
        if key in consumed:
            continue
        if isinstance(output, dict) and isinstance(output.get("output"), dict):
            output = output["output"]
        if isinstance(output, dict):
            result.append((None, output))
    return result


def _subject_names(plan_steps: list[dict[str, Any]], outputs: dict[str, Any]) -> dict[str, list[str]]:
    names = {}
    for step in plan_steps:
        if step.get("name") != "get_company_info":
            continue
        subject = str((step.get("inputs") or {}).get("ticker") or "")
        output = outputs.get(_text(step.get("id")))
        if isinstance(output, str):
            match = re.search(r"(?m)^\s*-?\s*Name:\s*([^\n]+)", output, re.IGNORECASE)
            name = match.group(1) if match else ""
        else:
            name = _text((output or {}).get("name") or (output or {}).get("longName")) if isinstance(output, dict) else ""
        words = [word for word in re.findall(r"[A-Za-z]{3,}", name) if word.lower() not in {"corporation", "inc", "company", "limited", "holdings", "corp", "ltd", "technology", "technologies"}]
        if subject:
            names[subject.upper()] = words
    return names


def _news_bound_to_subject(raw: dict[str, Any], subject: str | None, names: dict[str, list[str]]) -> bool:
    if not subject:
        return False
    from backend.research.news_event_quality import news_subject_match

    if news_subject_match(subject, _text(raw.get("title"))) == "headline":
        return True
    haystack = " ".join(_text(raw.get(key)) for key in ("title", "text", "snippet", "url"))
    aliases = [subject, *names.get(subject.upper(), [])]
    return any(re.search(rf"(?<![A-Za-z0-9]){re.escape(alias)}(?![A-Za-z0-9])", haystack, re.IGNORECASE) for alias in aliases)


def normalize_evidence(
    *,
    task_descriptors: list[TaskDescriptor],
    plan_steps: list[dict[str, Any]],
    agent_outputs: dict[str, Any],
    raw_evidence_by_task: dict[str, list[dict[str, Any]]],
) -> EvidenceNormalizationResult:
    descriptor_ids = {item.task_id for item in task_descriptors}
    step_index = {_text(step.get("id")): step for step in plan_steps}
    subject_names = _subject_names(plan_steps, agent_outputs)
    candidates: list[tuple[dict[str, Any], list[str], dict[str, Any] | None, str | None]] = []
    for task_id, items in raw_evidence_by_task.items():
        if not isinstance(items, list):
            continue
        for raw in items:
            if isinstance(raw, dict):
                step = step_index.get(_text(raw.get("step_id")))
                agent_name = _text(step.get("name")) if step and step.get("kind") == "agent" else None
                candidates.append((raw, [task_id] if task_id in descriptor_ids else [], step, agent_name))
    for step, output in _agent_output_entries(plan_steps, agent_outputs):
        bindings = [item for item in (_step_task_ids(step) if step else _strings(output.get("task_ids"))) if item in descriptor_ids]
        agent_name = _text(output.get("agent_name")) or (_text(step.get("name")) if step else "") or None
        for evidence_ordinal, raw in enumerate(output.get("evidence", []) if isinstance(output.get("evidence"), list) else []):
            if isinstance(raw, dict):
                raw = dict(raw)
                if agent_name and not _text(raw.get("title")) and any(
                    _text(raw.get(key)) for key in ("text", "snippet", "summary")
                ):
                    raw["title"] = f"{agent_name} evidence" if evidence_is_global(raw, agent_name) else f"{agent_name} evidence {evidence_ordinal + 1}"
                if not raw.get("text"):
                    raw["text"] = raw.get("snippet") or raw.get("summary")
                if output.get("as_of") is not None and _meta(raw).get("source_time_status") != "unknown" and not evidence_is_global(raw, agent_name or "") and not any(
                    raw.get(key) or _meta(raw).get(key)
                    for key in ("as_of", "timestamp", "published_date")
                ):
                    raw.setdefault("as_of", output["as_of"])
                explicit = _strings(raw.get("task_ids")) + _strings(raw.get("task_id"))
                merged = stable_unique([item for item in bindings + explicit if item in descriptor_ids])
                candidates.append((raw, merged, step, agent_name))

    evidence_index: dict[str, NormalizedEvidence] = {}
    rejected: list[RejectedEvidence] = []
    quality: list[str] = []
    for ordinal, (raw, inherited_bindings, step, inherited_agent) in enumerate(candidates):
        inputs = step.get("inputs") if step and isinstance(step.get("inputs"), dict) else {}
        declared_kinds = (step.get("evidence_kinds") or step.get("produces")) if step else None
        if isinstance(declared_kinds, str):
            declared_kinds = [declared_kinds]
        raw = evidence_contract_metadata(
            raw,
            producer_name=_text(step.get("name")) if step else _text(raw.get("agent_name") or inherited_agent),
            producer_kind=_text(step.get("kind")) if step else "agent" if raw.get("agent_name") or inherited_agent else "",
            required_evidence=declared_kinds or (inputs.get("required_evidence") if step and step.get("kind") == "tool" else None),
        )
        meta = _meta(raw)
        source_id = _text(raw.get("source_id") or meta.get("source_id"))
        explicit = _strings(raw.get("task_ids")) + _strings(raw.get("task_id"))
        task_ids = stable_unique([item for item in inherited_bindings + explicit if item in descriptor_ids])
        agent_name = _optional_text(raw.get("agent_name") or inherited_agent)
        if not source_id:
            rejected.append(RejectedEvidence(ordinal=ordinal, source_id=None, task_ids=task_ids, agent_name=agent_name, reason_code="missing_source_id"))
            continue
        if not task_ids:
            rejected.append(RejectedEvidence(ordinal=ordinal, source_id=source_id, task_ids=[], agent_name=agent_name, reason_code="missing_task_binding"))
            continue
        text = clean_research_text(_display_text(raw))
        if not text:
            rejected.append(RejectedEvidence(ordinal=ordinal, source_id=source_id, task_ids=task_ids, agent_name=agent_name, reason_code="empty_evidence_content"))
            continue
        kind = _kind(raw, step)
        payload = agent_outputs.get(_text(step.get("id"))) if step and step.get("kind") == "tool" else None
        if isinstance(payload, dict) and "output" in payload:
            payload = payload["output"]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (TypeError, ValueError):
                payload = {"text": payload}
        if isinstance(payload, list):
            payload = {"items": payload}
        payload = payload if isinstance(payload, dict) else {}
        row_payload = raw.get("structured_data")
        if raw.get("url") and isinstance(row_payload, dict) and row_payload:
            payload = {**{key: value for key, value in payload.items() if key in {"ticker", "source", "as_of", "currency", "frequency"}}, **row_payload}
        elif raw.get("url"):
            for row_key in ("items", "articles", "filings", "releases", "transcripts"):
                rows = payload.get(row_key)
                matched = next((item for item in rows if isinstance(item, dict) and raw["url"] in {item.get("url"), item.get("filing_url"), item.get("source_url")}), None) if isinstance(rows, list) else None
                if matched is not None:
                    payload = {**{key: value for key, value in payload.items() if key in {"ticker", "source", "as_of", "currency", "frequency"}}, **matched}
                    break
        if not payload:
            payload = raw.get("structured_data") if isinstance(raw.get("structured_data"), dict) else {}
        if not payload and any(key in meta for key in ("factor_beta", "risk_score", "rsi14", "metric_key", "metric", "value", "snapshot")):
            payload = dict(meta)
        if payload and step and step.get("kind") == "tool" and not raw.get("url"):
            text = clean_research_text(json.dumps(payload, ensure_ascii=False, default=str))
        quote_text = raw.get("text") or raw.get("snippet") or ""
        quote = parse_quote_payload(quote_text) if isinstance(quote_text, str) and "Current Price:" in quote_text else None
        if quote:
            kind = "price_snapshot"
            raw = {**raw, "market_price": quote["price"], "currency": quote.get("currency"), "as_of": quote.get("as_of") or raw.get("as_of"), "source_name": quote.get("source") or raw.get("source_name")}
        fact_metadata = payload.get("fact_metadata") if isinstance(payload.get("fact_metadata"), dict) else {}
        metric_metadata = next((
            item for values in fact_metadata.values() if isinstance(values, list)
            for item in values[:1] if isinstance(item, dict)
        ), {})
        raw_usage = _text(raw.get("usage") or meta.get("usage"))
        usage = raw_usage if raw_usage in {"raw", "fact", "summary", "diagnostic"} else (
            "summary" if _text(raw.get("id")).endswith(":summary") else "fact" if kind != "unknown" else "raw"
        )
        if step and step.get("kind") == "tool" and step.get("name") == "search":
            usage = "raw"
            meta = {**meta, "producer": "search", "verification": "discovery_only"}
        elif re.search(r"综合搜索结果|Search Results\s*[:(]", _display_text(raw), re.IGNORECASE):
            usage = "raw"
            meta = {**meta, "producer": "search", "verification": "discovery_only"}
        elif re.search(r"Official .+ (?:releases|press releases) page|Use when RSS feeds|official press releases index", _display_text(raw), re.IGNORECASE):
            usage = "raw"
            meta = {**meta, "producer": "source_index", "verification": "discovery_only"}
        event_quality = raw.get("event_quality") or meta.get("event_quality") or payload.get("event_quality")
        if isinstance(event_quality, dict):
            meta = {**meta, "event_quality": dict(event_quality)}
            if event_quality.get("evidence_role") != "reported_news":
                usage = "raw"
                meta["verification"] = "discovery_only"
        flow_arrays = [payload[key] for key in ("revenue", "gross_profit", "net_income", "eps", "operating_cash_flow") if isinstance(payload.get(key), list)]
        if flow_arrays and not any(value is not None for values in flow_arrays for value in values):
            usage = "raw"
        semantic = {
            "subject": raw.get("subject") or meta.get("subject") or meta.get("ticker") or metric_metadata.get("subject") or payload.get("subject") or payload.get("ticker") or (None if evidence_is_global(raw, _text(step.get("name")) if step else agent_name or "") else inputs.get("ticker") or ((step.get("subject_tickers") or [None])[0] if step and len(step.get("subject_tickers") or []) == 1 else None)),
            "metric": raw.get("metric") or meta.get("metric") or meta.get("metric_key"),
            "period_start": raw.get("period_start") or meta.get("start") or meta.get("period_start") or metric_metadata.get("period_start"),
            "period_end": raw.get("period_end") or meta.get("end") or meta.get("period_end") or meta.get("latest_period") or metric_metadata.get("period_end"),
            "frequency": raw.get("frequency") or meta.get("frequency") or payload.get("frequency"),
            "unit": raw.get("unit") or meta.get("unit") or payload.get("unit"),
            "currency": raw.get("currency") or meta.get("currency") or payload.get("currency"),
        }
        if kind == "news_context" and semantic["subject"] and usage != "summary" and not _news_bound_to_subject(raw, _optional_text(semantic["subject"]), subject_names):
            usage = "raw"
            meta = {**meta, "subject_binding": "unverified", "original_evidence_kind": kind}
            kind = "unknown"
        promoted = {
            key: _optional_text(raw.get(key) if raw.get(key) is not None else meta.get(key))
            for key in ("title", "source_name", "url", "as_of")
        }
        if not promoted["url"]:
            promoted["url"] = _optional_text(raw.get("source_url") or meta.get("source_url") or payload.get("source_url") or metric_metadata.get("source_url"))
        if not promoted["as_of"]:
            promoted["as_of"] = _optional_text(semantic["period_end"])
        if kind == "price_snapshot" and _market_price(raw, kind) is None:
            usage = "raw"
        evidence = NormalizedEvidence(
            source_id=source_id, task_ids=task_ids, agent_name=agent_name,
            kind=kind, text=text, market_price=_market_price(raw, kind), **promoted,
            usage=usage, metadata=dict(meta), structured_data=payload,
            **{key: _optional_text(value) for key, value in semantic.items()},
        )
        existing = evidence_index.get(source_id)
        if existing is None:
            evidence_index[source_id] = evidence
            continue
        existing_content = existing.model_dump(exclude={"task_ids"})
        new_content = evidence.model_dump(exclude={"task_ids"})
        if existing_content != new_content:
            rejected.append(RejectedEvidence(ordinal=ordinal, source_id=source_id, task_ids=task_ids, agent_name=agent_name, reason_code="evidence_id_content_conflict"))
            quality.append("evidence_id_content_conflict")
            continue
        merged_task_ids = stable_unique(existing.task_ids + task_ids)
        evidence_index[source_id] = existing.model_copy(update={"task_ids": merged_task_ids})

    by_task: dict[str, list[NormalizedEvidence]] = {item.task_id: [] for item in task_descriptors}
    for evidence in evidence_index.values():
        for task_id in evidence.task_ids:
            if task_id in by_task:
                by_task[task_id].append(evidence)
    return EvidenceNormalizationResult(
        evidence_by_task=by_task,
        evidence_index=evidence_index,
        rejected_evidence=rejected,
        quality_block_reasons=quality,
    )


def _dimension(raw: dict[str, Any], evidence: list[NormalizedEvidence], step: dict[str, Any] | None, agent_name: str) -> EvidenceDimension:
    raw_dimension = _text(raw.get("dimension"))
    kinds = {item.kind for item in evidence}
    mapped = {_KIND_DIMENSION.get(item.kind, "unknown") for item in evidence}
    compatible = False
    if raw_dimension in _DIMENSIONS:
        if raw_dimension == "valuation":
            compatible = bool(kinds & {"price_snapshot", "performance_comparison"}) and bool(kinds & {"company_profile", "fundamental_snapshot", "filing_context", "holdings_ownership", "earnings_estimates", "transcript_context"})
        elif raw_dimension == "catalyst":
            compatible = bool(kinds & {"event_calendar", "news_context"})
        else:
            compatible = mapped == {raw_dimension}
        if compatible:
            return raw_dimension  # type: ignore[return-value]
    if len(mapped) == 1:
        return next(iter(mapped))
    inputs = step.get("inputs") if isinstance(step, dict) and isinstance(step.get("inputs"), dict) else {}
    required = {_KIND_DIMENSION[item] for item in _strings(inputs.get("required_evidence")) if item in _KIND_DIMENSION}
    if len(required) == 1:
        return next(iter(required))
    return _AGENT_DIMENSION.get(agent_name, "unknown")


def _claim_content(claim: Claim) -> dict[str, Any]:
    return claim.model_dump(exclude={"claim_id"})


def _directional_family(stance: str) -> str | None:
    return stance if stance in {"bull", "bear", "neutral"} else None


def _build_conflicts(claims: dict[str, Claim]) -> list[ClaimConflict]:
    result: list[ClaimConflict] = []
    by_task: dict[str, list[Claim]] = {}
    for claim in claims.values():
        by_task.setdefault(claim.task_id, []).append(claim)
    for task_id, items in by_task.items():
        ordered = sorted(items, key=lambda item: item.claim_id)
        for index, left in enumerate(ordered):
            left_family = _directional_family(left.stance)
            if left_family is None:
                continue
            for right in ordered[index + 1:]:
                right_family = _directional_family(right.stance)
                if {left_family, right_family} != {"bull", "bear"}:
                    continue
                left_context = tuple(_text(value).casefold() for value in (left.subject, left.metric, left.horizon, left.scenario, left.dimension))
                right_context = tuple(_text(value).casefold() for value in (right.subject, right.metric, right.horizon, right.scenario, right.dimension))
                if any(value in {"", "unknown", "unspecified", "n/a", "未知"} for value in left_context + right_context) or left_context != right_context:
                    continue
                ids = [left.claim_id, right.claim_id]
                result.append(ClaimConflict(
                    conflict_id=f"conflict:{task_id}:{ids[0]}:{ids[1]}",
                    task_id=task_id, claim_ids=ids,
                    material=left.confidence >= 0.60 and right.confidence >= 0.60,
                    resolved=False, affects_direction=True,
                ))
    return result


def validate_claims(
    *,
    run_id: str,
    task_descriptors: list[TaskDescriptor],
    plan_steps: list[dict[str, Any]],
    agent_outputs: dict[str, Any],
    evidence_normalization: EvidenceNormalizationResult,
) -> ClaimValidationResult:
    task_ids = {item.task_id for item in task_descriptors}
    valid: dict[str, Claim] = {}
    rejected: list[RejectedClaim] = []
    quality: list[str] = []
    ordinal = 0
    for step, output in _agent_output_entries(plan_steps, agent_outputs):
        bindings = [item for item in (_step_task_ids(step) if step else _strings(output.get("task_ids"))) if item in task_ids]
        default_agent = _text(output.get("agent_name")) or (_text(step.get("name")) if step else "")
        raw_claims = output.get("raw_claims") if isinstance(output.get("raw_claims"), list) else []
        for raw in raw_claims:
            current_ordinal = ordinal
            ordinal += 1
            if not isinstance(raw, dict):
                rejected.append(RejectedClaim(ordinal=current_ordinal, reason_code="missing_claim_identity"))
                continue
            claim_id = _optional_text(raw.get("claim_id") or raw.get("id"))
            task_id = _text(raw.get("task_id"))
            if not task_id and len(bindings) == 1:
                task_id = bindings[0]
            agent_name = _text(raw.get("agent_name")) or default_agent
            original_text = _text(raw.get("text") or raw.get("claim"))
            text = clean_research_text(original_text)
            stance = _text(raw.get("stance")).lower()
            evidence_ids = _strings(raw.get("evidence_ids") or raw.get("source_ids"))
            if not text:
                rejected.append(RejectedClaim(ordinal=current_ordinal, claim_id=claim_id, task_id=task_id or None, agent_name=agent_name or None, reason_code="diagnostic_claim_text" if original_text else "empty_claim_text"))
                continue
            if stance not in _STANCE:
                rejected.append(RejectedClaim(ordinal=current_ordinal, claim_id=claim_id, task_id=task_id or None, agent_name=agent_name or None, reason_code="invalid_claim_stance"))
                continue
            try:
                confidence = float(raw.get("confidence"))
            except (TypeError, ValueError):
                confidence = math.nan
            if not math.isfinite(confidence) or not 0 <= confidence <= 1:
                rejected.append(RejectedClaim(ordinal=current_ordinal, claim_id=claim_id, task_id=task_id or None, agent_name=agent_name or None, reason_code="invalid_confidence"))
                continue
            if not task_id or task_id not in task_ids or not agent_name:
                rejected.append(RejectedClaim(ordinal=current_ordinal, claim_id=claim_id, task_id=task_id or None, agent_name=agent_name or None, reason_code="missing_claim_identity"))
                continue
            if not evidence_ids:
                rejected.append(RejectedClaim(ordinal=current_ordinal, claim_id=claim_id, task_id=task_id, agent_name=agent_name, reason_code="missing_evidence_reference"))
                continue
            referenced: list[NormalizedEvidence] = []
            reason: str | None = None
            for evidence_id in evidence_ids:
                evidence = evidence_normalization.evidence_index.get(evidence_id)
                if evidence is None:
                    reason = "invalid_claim_reference"
                    break
                if task_id not in evidence.task_ids:
                    reason = "cross_task_claim_reference"
                    break
                if evidence.metadata.get("subject_binding") == "unverified":
                    reason = "unverified_subject_reference"
                    break
                referenced.append(evidence)
            if reason:
                rejected.append(RejectedClaim(ordinal=current_ordinal, claim_id=claim_id, task_id=task_id, agent_name=agent_name, reason_code=reason))  # type: ignore[arg-type]
                if reason != "unverified_subject_reference":
                    quality.append(reason)
                continue
            claim_metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else _meta(raw)
            if claim_metadata.get("claim_type") in {"risk_score", "factor_exposure"} and not any(item.kind in {"risk_profile", "options_derivatives"} for item in referenced):
                rejected.append(RejectedClaim(ordinal=current_ordinal, claim_id=claim_id, task_id=task_id, agent_name=agent_name, reason_code="unsupported_risk_reference"))
                continue
            if stance in {"bull", "bear"} and any(isinstance(item.metadata.get("event_quality"), dict) and item.metadata["event_quality"].get("evidence_role") != "reported_news" for item in referenced):
                rejected.append(RejectedClaim(ordinal=current_ordinal, claim_id=claim_id, task_id=task_id, agent_name=agent_name, reason_code="unsupported_news_reference"))
                continue
            normalized_id = claim_id or f"claim:{run_id}:{task_id}:{agent_name}:{current_ordinal}"
            metadata = claim_metadata
            subjects = {item.subject for item in referenced if item.subject}
            claim = Claim(
                claim_id=normalized_id, task_id=task_id, agent_name=agent_name, text=text,
                stance=stance, dimension=_dimension(raw, referenced, step, agent_name),
                confidence=confidence, evidence_ids=evidence_ids,
                limitations=_strings(raw.get("limitations")),
                assertion_type="risk" if stance == "risk" else "fact" if stance in {"neutral", "unknown"} else "opinion",
                subject=_optional_text(raw.get("subject") or metadata.get("subject") or metadata.get("ticker") or (next(iter(subjects)) if len(subjects) == 1 else None)),
                metric=_optional_text(raw.get("metric") or metadata.get("metric") or metadata.get("claim_type")),
                horizon=_optional_text(raw.get("horizon") or metadata.get("horizon") or metadata.get("time_horizon")),
                scenario=_optional_text(raw.get("scenario") or metadata.get("scenario")),
            )
            existing = valid.get(normalized_id)
            if existing is None:
                valid[normalized_id] = claim
            elif _claim_content(existing) != _claim_content(claim):
                rejected.append(RejectedClaim(ordinal=current_ordinal, claim_id=normalized_id, task_id=task_id, agent_name=agent_name, reason_code="claim_id_content_conflict"))
                quality.append("claim_id_content_conflict")
    return ClaimValidationResult(
        valid_claims=valid, rejected_claims=rejected,
        conflicts=_build_conflicts(valid), quality_block_reasons=quality,
    )


def build_agent_findings(
    *,
    task_outcomes: list[TaskOutcome],
    plan_steps: list[dict[str, Any]],
    agent_outputs: dict[str, Any],
    claim_validation: ClaimValidationResult,
    evidence_normalization: EvidenceNormalizationResult,
) -> list[AgentFinding]:
    outcomes = {item.task_id: item for item in task_outcomes}
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for step, output in _agent_output_entries(plan_steps, agent_outputs):
        bindings = [item for item in (_step_task_ids(step) if step else _strings(output.get("task_ids"))) if item in outcomes]
        agent = _text(output.get("agent_name")) or (_text(step.get("name")) if step else "")
        if not agent:
            continue
        for task_id in bindings:
            grouped.setdefault((task_id, agent), []).append(output)
    findings: list[AgentFinding] = []
    for (task_id, agent), outputs in grouped.items():
        outcome = outcomes[task_id]
        claims = [item for item in claim_validation.valid_claims.values() if item.task_id == task_id and item.agent_name == agent]
        evidence_ids = stable_unique([evidence_id for claim in claims for evidence_id in claim.evidence_ids])
        has_evidence = any(item.agent_name == agent for item in evidence_normalization.evidence_by_task.get(task_id, []))
        fallback = any(bool(item.get("fallback_used")) for item in outputs)
        risks = stable_unique([value for item in outputs for value in _strings(item.get("risks"))])
        summaries = stable_unique([_text(item.get("summary")) for item in outputs if _text(item.get("summary"))])
        limitations = stable_unique([value for claim in claims for value in claim.limitations])
        if summaries and not claims:
            limitations.append("该研究维度暂未提供通过引用校验的原生论据，已保留对应事实。")
            fallback = True
        errors = stable_unique([_text(item.get("fallback_reason") or item.get("error_code")) for item in outputs if _text(item.get("fallback_reason") or item.get("error_code"))])
        if outcome.status == "blocked":
            status: TaskStatus = "blocked"
        elif claims:
            status = "answered" if outcome.status == "answered" else "partial"
        elif has_evidence:
            status = "partial"
        else:
            status = "unavailable"
        findings.append(AgentFinding(
            task_id=task_id, agent_name=agent, status=status,
            conclusion=claims[0].text if claims else None,
            claim_ids=[item.claim_id for item in claims], evidence_ids=evidence_ids,
            risks=risks, limitations=limitations, fallback_used=fallback,
            error_codes=errors or (["agent_output_unavailable"] if status == "unavailable" else []),
        ))
    return findings


def _min_status(left: TaskStatus, right: TaskStatus) -> TaskStatus:
    rank = {"answered": 0, "partial": 1, "unavailable": 2, "blocked": 3}
    return left if rank[left] >= rank[right] else right


def _response_payload(response: Any) -> Any:
    if isinstance(response, dict) and "raw" in response:
        raw = response.get("raw")
        parsed = response.get("parsed")
        if completion_metadata(raw)["finish_reason"].lower() in {"length", "max_tokens", "max_output_tokens"}:
            raise LLMCompletionError("llm_output_truncated")
        if not (getattr(raw, "tool_calls", None) and parsed is not None):
            final_completion_text(raw)
        if response.get("parsing_error") is not None or parsed is None:
            raise LLMCompletionError("llm_output_invalid")
        return parsed
    if isinstance(response, (StrictContract, dict)):
        return response
    content = final_completion_text(response)
    if isinstance(content, dict):
        return content
    text = _text(content)
    if not text:
        raise LLMCompletionError("llm_empty_output")
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```")
        text = text.removesuffix("```").strip()
    return json.loads(text)


async def _invoke_structured(
    *,
    prompt: str,
    context: LLMCallContext,
    schema: type[StrictContract],
    stage: str,
) -> StrictContract:
    """结构化解析失败时复用同一 context，修复请求不能重置预算。"""
    current_prompt = prompt
    last_error: Exception | None = None
    report_call = str(context.stage).startswith("report")
    token_key = "LANGGRAPH_SYNTHESIZE_REPORT_MAX_TOKENS" if report_call else "LANGGRAPH_SYNTHESIZE_MAX_TOKENS"
    timeout_key = "LANGGRAPH_SYNTHESIZE_REPORT_TIMEOUT_SEC" if report_call else "LANGGRAPH_SYNTHESIZE_TIMEOUT_SEC"
    acquire_key = "LANGGRAPH_SYNTHESIZE_REPORT_ACQUIRE_TIMEOUT_SEC" if report_call else "LANGGRAPH_SYNTHESIZE_ACQUIRE_TIMEOUT_SEC"
    max_tokens = max(512, env_int("LANGGRAPH_STRUCTURED_SYNTHESIS_MAX_TOKENS", env_int(token_key, 65536)))
    request_timeout = max(1, env_int(
        "LANGGRAPH_STRUCTURED_SYNTHESIS_REQUEST_TIMEOUT_SECONDS",
        env_int(timeout_key, env_int("LLM_REQUEST_TIMEOUT_SECONDS", 1200)),
    ))
    acquire_timeout = max(1, env_int("LANGGRAPH_STRUCTURED_SYNTHESIS_ACQUIRE_TIMEOUT_SECONDS", env_int(acquire_key, 120)))
    method = str(os.getenv("LANGGRAPH_STRUCTURED_SYNTHESIS_METHOD") or "json_schema").strip().lower()
    if method not in {"json_schema", "json_mode", "function_calling"}:
        raise ValueError("structured_synthesis_method_configuration_invalid")
    while context.budget.remaining > 0:
        response = await ainvoke_configured_llm(
            [HumanMessage(content=current_prompt)],
            context=context,
            temperature=0.1,
            max_tokens=max_tokens,
            request_timeout=request_timeout,
            acquire_timeout_seconds=acquire_timeout,
            acquire_token=True,
            client_transform=lambda client: client.with_structured_output(schema, method=method, include_raw=True),
        )
        try:
            return schema.model_validate(_response_payload(response))
        except Exception as exc:
            last_error = exc
            if isinstance(exc, LLMCompletionError) and exc.code in {"llm_output_truncated", "llm_empty_output"}:
                raise
            if context.budget.remaining <= 0:
                break
            current_prompt = (
                f"{prompt}\n\n上一次输出未通过 {stage} schema 校验。"
                "只返回符合 schema 的对象；不得添加输入中不存在的 ID。"
            )
    raise LLMCompletionError("llm_output_invalid") from last_error


def _failure_code(exc: Exception) -> str:
    if isinstance(exc, LLMCompletionError):
        return exc.code
    if isinstance(exc, (ValueError, AssertionError)):
        text = str(exc)
        if text.startswith(("task_synthesis_", "explanation_", "report_synthesis_")) and re.fullmatch(r"[a-z_]+", text):
            return text
        return "llm_output_invalid"
    return classify_llm_error(exc).code


def _fallback_task_result(
    *,
    outcome: TaskOutcome,
    findings: list[AgentFinding],
    claims: list[Claim],
    conflicts: list[ClaimConflict],
    evidence_normalization: EvidenceNormalizationResult,
    llm_failed: bool,
) -> TaskSynthesisResult:
    common = dict(
        task_id=outcome.task_id, title=outcome.title, priority=outcome.priority,
        order_index=outcome.order_index, request_frame_id=outcome.request_frame_id,
        render_kind=outcome.render_kind, render_group_id=outcome.render_group_id,
        subject=outcome.subject_label, operation=outcome.operation,
        missing_evidence=outcome.missing_evidence,
    )
    facts = [item for item in evidence_normalization.evidence_by_task.get(outcome.task_id, []) if item.usage == "fact"]
    if outcome.status == "blocked":
        return TaskSynthesisResult(
            **common, status="blocked", conclusion=None, claim_ids=[], evidence_ids=[],
            proposed_direction=None, direction_supporting_claim_ids=[], agent_names=[],
            agreements=[], disagreements=[], conflicts=[], risks=[], limitations=[],
            fallback_used=False, error_codes=outcome.error_codes,
        )

    families = stable_unique([
        family for item in claims if (family := _directional_family(item.stance))
    ])
    ordered = sorted(enumerate(claims), key=lambda item: (-item[1].confidence, item[0]))
    conclusion: str | None = None
    disagreements: list[str] = []
    proposal: str | None = None
    supporting: list[str] = []
    status = outcome.status
    selected_claims: list[Claim] = list(claims)
    if len(families) == 1 and ordered:
        conclusion = ordered[0][1].text
        proposal = families[0]
        supporting = [item.claim_id for item in selected_claims if item.stance == proposal]
    elif len(families) >= 2:
        selected_claims = list(claims)
        disagreements = [item.text for item in claims]
        status = outcome.status
    elif ordered:
        conclusion = ordered[0][1].text
    elif facts:
        status = "answered" if not outcome.missing_evidence and outcome.status == "answered" else "partial"
    else:
        status = "unavailable"

    limitations = stable_unique([
        value for item in claims for value in item.limitations
    ] + [value for item in findings for value in item.limitations])
    if llm_failed:
        limitations.append("模型合成不可用，结论来自已校验证据")
    claim_ids = [item.claim_id for item in selected_claims]
    evidence_ids = stable_unique([
        source_id for item in selected_claims for source_id in item.evidence_ids
    ])
    finding_fallback = any(item.fallback_used for item in findings)
    error_codes = list(outcome.error_codes)
    if llm_failed:
        error_codes.append("llm_unavailable")
    return TaskSynthesisResult(
        **common, status=status, conclusion=conclusion, claim_ids=claim_ids,
        evidence_ids=stable_unique(evidence_ids + [item.source_id for item in facts]), fact_ids=[item.source_id for item in facts], proposed_direction=proposal,
        direction_supporting_claim_ids=supporting,
        agent_names=[item.agent_name for item in findings], agreements=[],
        disagreements=disagreements, conflicts=conflicts,
        risks=stable_unique([value for item in findings for value in item.risks]),
        limitations=limitations, fallback_used=finding_fallback or llm_failed,
        error_codes=stable_unique(error_codes),
    )


async def synthesize_task_results(
    *,
    task_outcomes: list[TaskOutcome],
    findings: list[AgentFinding],
    claim_validation: ClaimValidationResult,
    evidence_normalization: EvidenceNormalizationResult,
    llm_call_context_factory: Callable[[TaskOutcome], LLMCallContext | None],
    requested_dimensions_by_task: dict[str, list[str]] | None = None,
) -> list[TaskSynthesisResult]:
    results: list[TaskSynthesisResult] = []
    for outcome in task_outcomes:
        task_findings = [item for item in findings if item.task_id == outcome.task_id]
        if outcome.status == "blocked":
            results.append(_fallback_task_result(
                outcome=outcome, findings=task_findings, claims=[], conflicts=[],
                evidence_normalization=evidence_normalization, llm_failed=False,
            ))
            continue
        claims = [item for item in claim_validation.valid_claims.values() if item.task_id == outcome.task_id]
        conflicts = [item for item in claim_validation.conflicts if item.task_id == outcome.task_id]
        task_evidence = evidence_normalization.evidence_by_task.get(outcome.task_id, [])
        materials = [item for item in task_evidence if item.usage == "fact" or item.usage == "raw" and (item.url or item.metadata.get("producer") == "search") and clean_research_text(item.text)]
        materials = [item for item in materials if item.metadata.get("subject_binding") != "unverified"]
        context = llm_call_context_factory(outcome) if claims or materials else None
        if context is None:
            results.append(_fallback_task_result(
                outcome=outcome, findings=task_findings, claims=claims, conflicts=conflicts,
                evidence_normalization=evidence_normalization, llm_failed=False,
            ))
            continue
        prompt_payload = {
            "task": {"task_id": outcome.task_id, "title": outcome.title, "status": outcome.status, "requested_dimensions": (requested_dimensions_by_task or {}).get(outcome.task_id, [])},
            "claims": [item.model_dump(mode="json") for item in claims],
            "evidence": [
                item.model_dump(mode="json")
                for item in materials
            ],
            "risks": stable_unique([value for item in task_findings for value in item.risks]),
            "limitations": stable_unique([value for item in task_findings for value in item.limitations]),
        }
        try:
            selection = await _invoke_structured(
                prompt=(
                    "按本任务要求形成有依据的分析，覆盖任务指出的每个维度，比较任务必须解释对象间差异。"
                    "claim_ids/fact_ids只能选择输入ID。explanation可解释输入事实与资料的经营、竞争、估值、催化、宏观机制或风险含义，"
                    "但必须提供explanation_evidence_ids，不能补造主体、财期、单位、数字或事件，不能自行给整体买卖方向。"
                    "优先解释机制，不重复数字；数值由确定性事实段展示。explanations可分段返回text/evidence_ids，"
                    "每段只表达其引用材料支持的分析，dimension从task.requested_dimensions中选择，并避免相同解释重复出现。"
                    "无相应材料必须明确缺失，原始诊断、搜索格式头和query_coverage不得进入正文。"
                    "原始资料是研究材料，不能将未证实内容写成确定事实。\n"
                    + json.dumps(prompt_payload, ensure_ascii=False, sort_keys=True)
                ),
                context=context, schema=_TaskSynthesisSelection, stage="task_synthesis",
            )
            assert isinstance(selection, _TaskSynthesisSelection)
            claim_by_id = {item.claim_id: item for item in claims}
            selected_ids = selection.claim_ids
            if not selected_ids and not selection.fact_ids and not selection.explanation and not selection.explanations:
                raise LLMCompletionError("llm_empty_output")
            if any(item not in claim_by_id for item in selected_ids):
                raise ValueError("task_synthesis_unknown_claim_id")
            if selection.conclusion_claim_id and selection.conclusion_claim_id not in selected_ids:
                raise ValueError("task_synthesis_conclusion_not_selected")
            support = selection.direction_supporting_claim_ids
            if any(item not in selected_ids for item in support):
                raise ValueError("task_synthesis_direction_reference_invalid")
            if selection.proposed_direction is None and support:
                raise ValueError("task_synthesis_direction_without_proposal")
            if selection.proposed_direction is not None and (
                not support
                or any(claim_by_id[item].stance != selection.proposed_direction for item in support)
            ):
                raise ValueError("task_synthesis_direction_stance_mismatch")
            selected_claims = [claim_by_id[item] for item in selected_ids]
            material_index = {item.source_id: item for item in materials}
            if any(source_id not in material_index or material_index[source_id].usage != "fact" for source_id in selection.fact_ids):
                raise ValueError("task_synthesis_unknown_evidence_id")
            explanations = list(selection.explanations)
            if selection.explanation:
                explanations.insert(0, {"text": selection.explanation, "evidence_ids": selection.explanation_evidence_ids})
            explanation_errors, explanation_texts = [], []
            for ordinal, explanation in enumerate(explanations):
                explanation_text = _text(explanation.get("text")) if isinstance(explanation, dict) else ""
                explanation_ids = _strings(explanation.get("evidence_ids")) if isinstance(explanation, dict) else []
                try:
                    if not explanation_text or not explanation_ids:
                        raise ValueError("task_synthesis_explanation_missing_evidence")
                    if any(source_id not in material_index for source_id in explanation_ids):
                        raise ValueError("task_synthesis_unknown_evidence_id")
                    referenced = [material_index[source_id] for source_id in explanation_ids]
                    _validate_explanation(explanation_text, referenced, selected_claims)
                except (ValueError, AssertionError) as exc:
                    explanation_errors.append(_failure_code(exc))
                    continue
                explanation_claim = Claim(
                    claim_id=f"synthesis:{outcome.task_id}:explanation" + (f":{ordinal}" if ordinal else ""), task_id=outcome.task_id,
                    agent_name="research_analyst", text=explanation_text, stance="unknown",
                    assertion_type="opinion", directional=False,
                    dimension=_dimension({}, referenced, None, "research_analyst"), confidence=min([claim.confidence for claim in selected_claims] or [0.6]),
                    evidence_ids=explanation_ids,
                    limitations=["解释基于列出的材料，不替代原始公告或数据核验。"] if any(item.usage == "raw" for item in referenced) else [],
                    subject=outcome.subject_label,
                    metric=explanation.get("dimension") if explanation.get("dimension") in (requested_dimensions_by_task or {}).get(outcome.task_id, []) else None,
                )
                claim_validation.valid_claims[explanation_claim.claim_id] = explanation_claim
                selected_claims.append(explanation_claim)
                selected_ids.append(explanation_claim.claim_id)
                explanation_texts.append(explanation_text)
            conclusion = (
                claim_by_id[selection.conclusion_claim_id].text
                if selection.conclusion_claim_id else None
            )
            if explanation_texts:
                conclusion = "\n".join(explanation_texts)
            discovery_used = any(material_index[source_id].usage == "raw" for claim in selected_claims for source_id in claim.evidence_ids if source_id in material_index)
            complete = bool(conclusion and not discovery_used and not explanation_errors and not outcome.missing_evidence and not set(outcome.required_step_ids).difference(outcome.successful_step_ids))
            status = "answered" if complete else outcome.status if conclusion else _min_status(outcome.status, "partial")
            if discovery_used:
                status = "partial"
            finding_fallback = any(item.fallback_used for item in task_findings)
            results.append(TaskSynthesisResult(
                task_id=outcome.task_id, title=outcome.title, priority=outcome.priority,
                order_index=outcome.order_index, request_frame_id=outcome.request_frame_id,
                render_kind=outcome.render_kind, render_group_id=outcome.render_group_id,
                status=status, conclusion=conclusion, claim_ids=selected_ids,
                fact_ids=[item.source_id for item in task_evidence if item.usage == "fact"],
                selected_fact_ids=stable_unique(selection.fact_ids),
                missing_evidence=outcome.missing_evidence, subject=outcome.subject_label, operation=outcome.operation,
                evidence_ids=stable_unique([
                    source_id for item in selected_claims for source_id in item.evidence_ids
                ]),
                proposed_direction=selection.proposed_direction,
                direction_supporting_claim_ids=support,
                agent_names=[item.agent_name for item in task_findings], agreements=[],
                disagreements=[item.text for item in claims] if len({item.stance for item in claims if _directional_family(item.stance)}) > 1 else [],
                conflicts=conflicts,
                risks=stable_unique([value for item in task_findings for value in item.risks]),
                limitations=stable_unique([value for item in task_findings for value in item.limitations] + [value for claim in selected_claims for value in claim.limitations]),
                fallback_used=finding_fallback or bool(explanation_errors), error_codes=stable_unique(outcome.error_codes + explanation_errors + (["structured_selection_invalid"] if explanation_errors else [])),
            ))
            if explanation_errors:
                results[-1].status = "partial"
                results[-1].limitations.append("部分模型解释未通过事实绑定校验，已移除对应段落；其它已验证事实与论据仍保留。")
        except Exception as exc:
            fallback = _fallback_task_result(
                outcome=outcome, findings=task_findings, claims=claims, conflicts=conflicts,
                evidence_normalization=evidence_normalization, llm_failed=True,
            )
            code = _failure_code(exc)
            fallback.error_codes = stable_unique([value for value in fallback.error_codes if value != "llm_unavailable"] + [code])
            if isinstance(exc, (ValueError, AssertionError)):
                fallback.error_codes = stable_unique(fallback.error_codes + ["structured_selection_invalid"])
                fallback.limitations = stable_unique([value for value in fallback.limitations if value != "模型合成不可用，结论来自已校验证据"] + ["模型选择的引用未通过合同校验，已保留原有受支持事实与论据。"])
            results.append(fallback)
    return results


async def synthesize_report_draft(
    *,
    task_results: list[TaskSynthesisResult],
    claim_validation: ClaimValidationResult,
    evidence_normalization: EvidenceNormalizationResult,
    llm_call_context_factory: Callable[[], LLMCallContext | None],
) -> ReportSynthesisDraft:
    conclusions = [item.conclusion for item in task_results if item.conclusion]
    fallback_overall = None
    if len(task_results) == 1 and conclusions:
        fallback_overall = conclusions[0]
    elif conclusions:
        fallback_overall = f"本轮已有 {len(conclusions)}/{len(task_results)} 项受支持结论；各对象和维度分别呈现。"
    context = llm_call_context_factory() if conclusions else None
    overall = fallback_overall
    report_fallback = False
    report_errors = []
    if context is not None:
        try:
            selection = await _invoke_structured(
                prompt=(
                    "基于受支持的分任务结论生成简洁总判断。只能使用输入内容；"
                    "supporting_task_ids 必须来自输入。存在未解决冲突时必须明确无法形成统一判断。\n"
                    + json.dumps({
                        "task_results": [item.model_dump(mode="json") for item in task_results],
                        "evidence": [item.model_dump(mode="json") for item in evidence_normalization.evidence_index.values() if item.usage == "fact"],
                        "conflicts": [item.model_dump(mode="json") for item in claim_validation.conflicts],
                    }, ensure_ascii=False, sort_keys=True)
                ),
                context=context, schema=_ReportSynthesisSelection, stage="report_synthesis",
            )
            assert isinstance(selection, _ReportSynthesisSelection)
            supported = {
                item.task_id for item in task_results if item.conclusion and item.claim_ids
            }
            if any(item not in supported for item in selection.supporting_task_ids):
                raise ValueError("report_synthesis_unknown_task_id")
            has_material_conflict = any(
                item.material and not item.resolved for item in claim_validation.conflicts
            )
            if has_material_conflict and len(task_results) > 1:
                overall = fallback_overall
                report_fallback = True
            else:
                overall = selection.overall_conclusion
                report_fallback = False
        except Exception as exc:
            overall = fallback_overall
            report_fallback = True
            report_errors.append(_failure_code(exc))
    citation_ids = stable_unique([
        evidence_id
        for result in task_results
        for claim_id in result.claim_ids
        if (claim := claim_validation.valid_claims.get(claim_id)) is not None
        for evidence_id in claim.evidence_ids
    ] + [source_id for result in task_results for source_id in result.fact_ids])
    return ReportSynthesisDraft(
        schema_version=SCHEMA_VERSION,
        status=aggregate_task_status([item.status for item in task_results]),
        overall_conclusion=overall, task_results=task_results,
        claim_index=claim_validation.valid_claims,
        evidence_index=evidence_normalization.evidence_index,
        citation_ids=citation_ids, conflicts=claim_validation.conflicts,
        disagreements=stable_unique([value for item in task_results for value in item.disagreements]),
        risks=stable_unique([value for item in task_results for value in item.risks]),
        limitations=stable_unique([value for item in task_results for value in item.limitations]),
        fallback_used=report_fallback,
        error_codes=report_errors,
    )


def evaluate_synthesis_quality(
    *,
    draft: ReportSynthesisDraft,
    requested_task_ids: list[NonEmptyStr],
    evidence_index: dict[NonEmptyStr, NormalizedEvidence],
    rendered_task_ids: list[NonEmptyStr] | None = None,
    structural_block_reasons: list[NonEmptyStr] | None = None,
    require_claims: bool = True,
) -> SynthesisQualityGateResult:
    block = list(structural_block_reasons or [])
    result_ids = [item.task_id for item in draft.task_results]
    if len(requested_task_ids) != len(set(requested_task_ids)) or len(result_ids) != len(set(result_ids)):
        block.append("duplicate_task")
    if requested_task_ids != result_ids:
        block.append("missing_task")
    orders = [item.order_index for item in draft.task_results]
    if len(orders) != len(set(orders)):
        block.append("duplicate_order_index")
    if any(key != value.claim_id for key, value in draft.claim_index.items()):
        block.append("claim_index_key_mismatch")
    if any(key != value.source_id for key, value in draft.evidence_index.items()):
        block.append("evidence_index_key_mismatch")
    if evidence_index != draft.evidence_index:
        block.append("evidence_index_mismatch")
    expected_citations: list[str] = []
    for result in draft.task_results:
        for claim_id in result.claim_ids:
            claim = draft.claim_index.get(claim_id)
            if claim is None:
                block.append("invalid_claim_reference")
                continue
            for source_id in claim.evidence_ids:
                evidence = draft.evidence_index.get(source_id)
                if evidence is None:
                    block.append("invalid_claim_reference")
                elif claim.task_id not in evidence.task_ids:
                    block.append("cross_task_claim_reference")
                elif source_id not in expected_citations:
                    expected_citations.append(source_id)
    for result in draft.task_results:
        for source_id in result.fact_ids:
            evidence = draft.evidence_index.get(source_id)
            if evidence is None or result.task_id not in evidence.task_ids or evidence.usage != "fact":
                block.append("invalid_fact_reference")
            elif source_id not in expected_citations:
                expected_citations.append(source_id)
    if require_claims and not any(result.claim_ids for result in draft.task_results):
        block.append("no_supported_report_claims")
    if draft.citation_ids != expected_citations:
        block.append("citation_set_mismatch")
    if rendered_task_ids is not None and rendered_task_ids != result_ids:
        block.append("renderer_task_coverage_mismatch")
    block = stable_unique(block)
    if block:
        return SynthesisQualityGateResult(state="block", reasons=block)
    degraded: list[str] = []
    if any(item.status != "answered" for item in draft.task_results):
        degraded.append("task_not_answered")
    if draft.fallback_used or any(item.fallback_used for item in draft.task_results):
        degraded.append("fallback_used")
    if any(item.material and not item.resolved for item in draft.conflicts):
        degraded.append("unresolved_material_conflict")
    if require_claims and not draft.overall_conclusion:
        degraded.append("missing_overall_conclusion")
    if require_claims and not any(item.conclusion and item.claim_ids for item in draft.task_results):
        degraded.append("missing_supported_task_conclusion")
    return SynthesisQualityGateResult(state="warn" if degraded else "pass", reasons=degraded)


def finalize_report_synthesis(
    *, draft: ReportSynthesisDraft, final_gate: SynthesisQualityGateResult,
) -> ReportSynthesisResult:
    return ReportSynthesisResult(**draft.model_dump(), degraded=final_gate.state != "pass")


__all__ = [
    "build_agent_findings", "evaluate_synthesis_quality", "finalize_report_synthesis",
    "normalize_evidence", "synthesize_report_draft", "synthesize_task_results",
    "validate_claims",
]
