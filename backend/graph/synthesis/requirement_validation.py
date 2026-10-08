"""把回答完整度绑定到编译后的用户要求，而非引用数量。"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from backend.graph.synthesis.contracts import Claim, NormalizedEvidence, ReportSynthesisDraft, TaskSynthesisResult, stable_unique
from backend.research.filing_evidence import disclosure_sections
from backend.graph.synthesis.requirement_support import FINANCIAL_METRICS, attached_source_policy_reasons, calculation_record, control_support_reasons, exact_support_reasons, metric_record, metric_supports, period_for, presentation_reasons, time_scope_matches


def _present(value: Any) -> bool:
    return value not in (None, "", [], {}) and str(value).strip().lower() not in {"unknown", "n/a", "none", "null"}


def _payload(evidence: NormalizedEvidence) -> dict[str, Any]:
    return {**evidence.metadata, **evidence.structured_data}


def _reliable_task_evidence(evidence: NormalizedEvidence, task: TaskSynthesisResult, subjects: list[str]) -> bool:
    if evidence.usage != "fact" or task.task_id not in evidence.task_ids or evidence.metadata.get("subject_binding") == "unverified":
        return False
    allowed = {str(subject).upper() for subject in subjects if subject}
    global_context = evidence.kind == "macro_context" or evidence.metadata.get("entity_scope") in {"global", "macro"}
    return not evidence.subject or not allowed or evidence.subject.upper() in allowed or global_context


def claim_has_reliable_sources(claim: Claim, task: TaskSynthesisResult, evidence_index: dict[str, NormalizedEvidence], *, subjects: list[str] | None = None) -> bool:
    """每个引用都须真实、属于当前任务及其主体；补充事实无需都属于同一维度。"""
    if claim.task_id != task.task_id or not claim.evidence_ids:
        return False
    scope = subjects if subjects is not None else task.requested_subjects
    return all(source_id in evidence_index and _reliable_task_evidence(evidence_index[source_id], task, scope) for source_id in claim.evidence_ids)


def overall_conclusion_block_reasons(draft: ReportSynthesisDraft) -> list[str]:
    """只有完整任务与全部可靠的已选论据才能作为成立的总判断输入。"""
    reasons = []
    if draft.status != "answered" or any(task.status != "answered" or task.missing_evidence or task.missing_requirements or any(check.get("status") != "answered" for check in task.requirement_results)
        or {item.get("requirement_id") for item in task.answer_requirements} != {item.get("requirement_id") for item in task.requirement_results}
        for task in draft.task_results):
        reasons.append("answer_requirements_incomplete")
    if not any(task.conclusion and task.claim_ids for task in draft.task_results):
        reasons.append("missing_supported_task_conclusion")
    for task in draft.task_results:
        if any(claim_id not in draft.claim_index or not claim_has_reliable_sources(draft.claim_index[claim_id], task, draft.evidence_index) for claim_id in task.claim_ids):
            reasons.append("unverified_task_claim_sources")
            break
    return reasons


def evidence_is_document_index(evidence: NormalizedEvidence) -> bool:
    payload = _payload(evidence)
    if disclosure_sections(payload):
        return False
    if payload.get("content_read") is True and any(_present(payload.get(key)) for key in ("document_body", "body", "content")):
        return False
    if "content_read" in payload and evidence.kind in {"filing_context", "document_context"}:
        return True
    content_type = str(payload.get("content_type") or payload.get("document_type") or "").lower()
    if content_type in {"filing_index", "disclosure_index", "index", "directory"}:
        return True
    return bool(re.search(r"^(?:SEC EDGAR .+ filing\. Filed:|(?:HK|CN) local disclosure .+\. Filed:)", evidence.text))


def _supports_dimension(evidence: NormalizedEvidence, dimension: str) -> bool:
    if evidence.usage != "fact" or evidence.metadata.get("subject_binding") == "unverified" or evidence_is_document_index(evidence):
        return False
    payload = _payload(evidence)
    if dimension in {"business_model", "competition"}:
        if "content_read" in payload:
            sections = disclosure_sections(payload)
            return bool(sections.get("business") if dimension == "business_model" else sections.get("competition")) or (
                evidence.kind == "document_context" and payload.get("content_read") is True
                and any(_present(payload.get(key)) for key in ("document_body", "body", "content"))
            )
        explicit = evidence.metric == dimension or payload.get("dimension") == dimension
        body = any(_present(payload.get(key)) for key in ("document_body", "body", "sections", "business_description", "longBusinessSummary", "description", "competitive_landscape", "competitors"))
        if dimension == "competition":
            body = any(_present(payload.get(key)) for key in ("document_body", "body", "sections", "competitive_landscape", "competitors"))
        return bool(explicit or body)
    if dimension in {"valuation", "valuation_sanity", "valuation_reasonableness"}:
        keys = {"trailingPE", "forwardPE", "priceToSalesTrailing12Months", "enterpriseToEbitda", "priceToBook", "fcf_yield", "pe_ratio", "valuation_multiple"}
        return any(_present(payload.get(key)) for key in keys) or bool(re.search(r"(?:P/?E|P/?S|EV/|市盈率|市销率|市净率|现金流收益率)\s*[:：=]?\s*\d", evidence.text, re.IGNORECASE))
    return True


def _financial_periods(evidence: NormalizedEvidence) -> set[tuple[str, str, str]]:
    payload = _payload(evidence)
    rows = [payload]
    metadata = payload.get("fact_metadata")
    if isinstance(metadata, dict):
        rows.extend(row for items in metadata.values() if isinstance(items, list) for row in items if isinstance(row, dict))
    periods = set()
    for row in rows:
        start = row.get("period_start") or evidence.period_start
        end = row.get("period_end") or evidence.period_end
        unit = row.get("unit") or row.get("currency") or evidence.unit or evidence.currency
        if start and end and unit:
            periods.add((str(start), str(end), str(unit)))
    return periods


def _claim_matches_requirement(claim: Claim, requirement: dict[str, Any]) -> bool:
    dimension = str(requirement.get("dimension") or "")
    requirement_id = str(requirement.get("requirement_id") or "")
    if requirement_id in claim.requirement_ids and (not dimension or claim.metric == dimension):
        return True
    if dimension and claim.metric == dimension:
        return True
    if dimension == "risk_level" and claim.dimension == "risk" and claim.metric in {"risk_score", "factor_exposure", "stress_test"}:
        return True
    # 原生财务指标与旧式无维度解释可构成部分支持；组件核验另行决定是否完整。
    return dimension == "fundamental_quality" and claim.dimension == "fundamental" and claim.metric in {
        None, "growth_quality", "cash_flow_quality", "eps_revision", "balance_sheet_risk",
    }


def _financial_component_supported(component: str, claims: list[Claim], evidence_index: dict[str, NormalizedEvidence]) -> bool:
    patterns = {
        "revenue": r"营收|收入|\b(?:revenue|sales)\b",
        "net_income": r"净利(?:润)?|利润端|\bnet\s+(?:income|profit)\b",
        "cash_flow": r"现金流|\b(?:cash\s*flow|CFO|FCF)\b",
    }
    metrics = {"revenue": {"revenue"}, "net_income": {"net_income"}, "cash_flow": {"operating_cash_flow", "free_cash_flow"}}
    if component not in patterns:
        return False
    for claim in claims:
        if not re.search(patterns[component], claim.text, re.IGNORECASE):
            continue
        for source_id in claim.evidence_ids:
            evidence = evidence_index[source_id]
            payload = _payload(evidence)
            if evidence.metric in metrics[component] or payload.get("metric_key") in metrics[component]:
                return True
            for key in metrics[component]:
                values = payload.get(key)
                if isinstance(values, list) and any(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values):
                    return True
                if isinstance(values, (int, float)) and not isinstance(values, bool):
                    return True
    return False


def _attribute_present(evidence: NormalizedEvidence, attribute: str) -> bool:
    payload = _payload(evidence)
    if attribute == "as_of":
        return payload.get("source_time_status") != "unknown" and _present(evidence.as_of or payload.get("as_of"))
    if attribute == "currency":
        return _present(evidence.currency) or _present(payload.get("currency")) or any(isinstance(row, dict) and _present(row.get("currency")) for row in payload.get("dividend_announcements") or [])
    if attribute == "source_timestamp":
        return payload.get("source_time_status") != "unknown" and (_present(evidence.as_of) or any(_present(payload.get(key)) for key in ("source_timestamp", "source_time", "as_of", "timestamp")))
    if attribute == "market_session":
        return any(_present(payload.get(key)) for key in ("market_session", "marketSession", "market_state", "marketState", "session", "is_after_hours", "is_extended_hours"))
    if attribute == "end_close":
        if _present(payload.get("end_close")):
            return True
        return evidence.kind == "price_snapshot" and evidence.market_price is not None and payload.get("market_session") in {"regular_close", "continuous_close"}
    if attribute in {"amount_per_share", "announced_at", "payable_date", "record_date", "frequency"}:
        announcements = payload.get("dividend_announcements") or []
        if announcements:
            return any(isinstance(row, dict) and _present(row.get(attribute)) for row in announcements)
    return _present(payload.get(attribute))


def _comparable_financial_periods(periods: list[set[tuple[str, str, str]]], scope: dict) -> bool:
    if periods and set.intersection(*periods):
        return True
    if scope.get("kind") != "fiscal_year" or not periods or any(not rows for rows in periods):
        return False
    # 52/53周财年可落在不同日期；仍要求全年长度、同币种及相近年末。
    annual = []
    for rows in periods:
        parsed = []
        for start, end, unit in rows:
            try:
                first, last = date.fromisoformat(start), date.fromisoformat(end)
            except ValueError:
                continue
            if 350 <= (last - first).days + 1 <= 380:
                parsed.append((last, unit))
        annual.append(parsed)
    return bool(annual[0]) and any(all(any(unit == other_unit and abs((last - other_end).days) <= 35 for other_end, other_unit in rows) for rows in annual[1:]) for last, unit in annual[0])


def _window_coverage(evidence: NormalizedEvidence, window: dict[str, Any]) -> dict[str, Any] | None:
    payload = _payload(evidence)
    scope = payload.get("coverage_window")
    # 请求参数仅声明义务；只有采集结果返回的窗口才能证明实际执行范围。
    if not isinstance(scope, dict) or not scope.get("as_of") or scope.get("scope") in {None, "request", "requested"}:
        return None
    requested = window.get("value")
    if not isinstance(requested, (int, float)) or requested <= 0:
        return None
    hours = requested * (24 if window.get("unit") == "days" else 1)
    matches = scope.get("direction") == window.get("direction") and scope.get("unit") == window.get("unit") and scope.get("value") == requested
    if window.get("direction") == "future":
        supplied = scope.get("days_ahead")
        matches = matches or isinstance(supplied, (int, float)) and supplied * 24 >= hours
    else:
        supplied = scope.get("hours_back", scope.get("max_age_hours"))
        matches = matches or isinstance(supplied, (int, float)) and supplied == hours
    if not matches:
        return None
    exhaustive = scope.get("exhaustive") is True and scope.get("scope") != "returned_articles"
    return {"status": "complete" if exhaustive else "bounded", "scope": scope["scope"], "exhaustive": exhaustive, "as_of": scope["as_of"]}


def evaluate_answer_requirements(
    *, result: TaskSynthesisResult, requirements: list[dict[str, Any]],
    evidence_index: dict[str, NormalizedEvidence], claim_index: dict[str, Claim],
    subjects: list[str],
    displayed_evidence_ids: list[str] | None = None,
    displayed_claim_ids: list[str] | None = None,
) -> None:
    """只认将被展示的事实/论据；无法证明满足的义务保持缺失。"""
    result.answer_requirements = requirements
    result.requirement_results = []
    requirement_ids = {item.get("requirement_id") for item in requirements}
    result.missing_requirements = [item for item in result.missing_requirements if item.get("requirement_id") not in requirement_ids]
    selected_claims = [claim_index[claim_id] for claim_id in result.claim_ids if claim_id in claim_index]
    available_ids = stable_unique(result.fact_ids + [source_id for claim in selected_claims for source_id in claim.evidence_ids])
    shown_claims = [claim for claim in selected_claims if displayed_claim_ids is None or claim.claim_id in displayed_claim_ids]
    shown_ids = available_ids if displayed_evidence_ids is None else stable_unique(displayed_evidence_ids + [source_id for claim in shown_claims for source_id in claim.evidence_ids])
    for requirement in requirements:
        requirement_id = str(requirement.get("requirement_id") or "")
        dimension = str(requirement.get("dimension") or "")
        kinds = set(requirement.get("evidence_kinds") or [])
        subject = requirement.get("subject")
        scope = [str(subject)] if subject and requirement.get("kind") != "comparison" and result.render_kind != "compare" else subjects
        available_facts = [evidence_index[source_id] for source_id in available_ids if source_id in evidence_index
                 and result.task_id in evidence_index[source_id].task_ids
                 and _reliable_task_evidence(evidence_index[source_id], result, scope)
                 and (not kinds or evidence_index[source_id].kind in kinds
                      or requirement.get("metric") in FINANCIAL_METRICS
                      and metric_record(evidence_index[source_id], requirement["metric"]) is not None)
                 and (not subject or requirement.get("kind") == "comparison" or result.render_kind == "compare"
                      or evidence_index[source_id].subject == subject
                      or evidence_index[source_id].kind == "document_context"
                      and evidence_index[source_id].metadata.get("shared_document")
                      and requirement.get("metric") not in FINANCIAL_METRICS)
                 and (calculation_record(evidence_index[source_id], requirement) is not None if requirement.get("calculation")
                      else metric_supports(evidence_index[source_id], str(requirement.get("metric") or "")))
                 and _supports_dimension(evidence_index[source_id], dimension)]
        fiscal_scope = requirement.get("time_scope") or {}
        if requirement.get("metric") in FINANCIAL_METRICS and fiscal_scope.get("kind") in {"fiscal_year", "fiscal_quarter"}:
            # 以已选择的完整财期锚定跨来源事实，供应商的近似日期不能形成第二套“同季”答案。
            anchors: dict[str | None, set[str]] = {}
            for evidence in available_facts:
                selected = _payload(evidence).get("selected_period")
                if selected and time_scope_matches(evidence, fiscal_scope, metric_record(evidence, requirement["metric"])):
                    anchors.setdefault(evidence.subject, set()).add(selected)
            available_facts = [evidence for evidence in available_facts
                if len(anchors.get(evidence.subject, set())) != 1
                or period_for(evidence, calculation_record(evidence, requirement) if requirement.get("calculation")
                              else metric_record(evidence, requirement["metric"]))[1] in anchors[evidence.subject]]
        facts = [evidence for evidence in available_facts if evidence.source_id in shown_ids]
        supported_ids = {fact.source_id for fact in facts}
        explicit_binding = bool(requirement.get("requires_explicit_binding")) or requirement.get("kind") == "event_window" or requirement_id.endswith(":event_grouping")
        claims = [claim for claim in shown_claims if
                  _claim_matches_requirement(claim, requirement)
                  and (not explicit_binding or requirement_id in claim.requirement_ids)
                  and (not requirement.get("requires_analysis") or claim.agent_name == "research_analyst" or claim.assertion_type in {"opinion", "risk"})
                  and bool(set(claim.evidence_ids) & supported_ids)
                  and claim_has_reliable_sources(claim, result, evidence_index, subjects=scope)]
        control_reasons = control_support_reasons(requirement, result, facts)
        reasons = exact_support_reasons(requirement, facts) if control_reasons is None else list(control_reasons)
        reasons.extend(attached_source_policy_reasons(requirement, result, facts))
        reasons.extend(presentation_reasons(requirement, facts))
        if not facts and control_reasons is None:
            reasons.append("requirement_evidence_not_presented" if available_facts else "requirement_evidence_missing")
        for attribute in requirement.get("attributes") or []:
            if not any(_attribute_present(fact, str(attribute)) for fact in facts):
                reasons.append(f"missing_attribute:{attribute}")
        if requirement.get("requires_analysis") and not claims and control_reasons is None:
            reasons.append("requirement_explanation_missing")
        if requirement.get("kind") == "constraint" and control_reasons is None and not claims:
            reasons.append("requirement_constraint_unverified")
        components = requirement.get("components") if isinstance(requirement.get("components"), list) else []
        if requirement.get("source_text"):
            missing_components = [component for component in components if f"requirement_component_missing:{component}" in reasons]
        else:
            missing_components = [component for component in components if not _financial_component_supported(str(component), claims, evidence_index)]
            reasons.extend(f"requirement_component_missing:{component}" for component in missing_components)
        if requirement.get("kind") == "conclusion" and not result.conclusion:
            reasons.append("requirement_conclusion_missing")
        if requirement.get("kind") == "comparison" or result.render_kind == "compare":
            compared = {fact.subject for fact in facts}
            if any(ticker not in compared for ticker in subjects):
                reasons.append("comparison_subject_evidence_missing")
            if requirement.get("requires_analysis") and not any(set(subjects).issubset({evidence_index[source_id].subject for source_id in claim.evidence_ids}) for claim in claims):
                reasons.append("comparison_explanation_missing")
            if dimension in {"cash_flow_quality", "fundamental_quality", "financial_performance", "earnings_quality"} and len(subjects) > 1:
                periods = [set().union(*[_financial_periods(fact) for fact in facts if fact.subject == ticker]) for ticker in subjects]
                if not _comparable_financial_periods(periods, requirement.get("time_scope") or {}):
                    reasons.append("comparison_period_or_currency_unverified")
        window = requirement.get("time_window")
        window_coverage = None
        if isinstance(window, dict):
            windows = [covered for fact in facts if (covered := _window_coverage(fact, window)) is not None]
            window_coverage = next((covered for covered in windows if covered["exhaustive"]), next(iter(windows), None))
            if window_coverage is None:
                reasons.append("requirement_time_window_unverified")
            elif requirement.get("requires_exhaustive") and not window_coverage["exhaustive"]:
                reasons.append("requirement_time_window_not_exhaustive")
            elif not window_coverage["exhaustive"]:
                result.limitations = stable_unique([*result.limitations, "时间范围仅覆盖本轮取得的供应商资料，不能据此断言窗口内没有其它事件；预期日历日期仍需公司或官方确认。"])
        if isinstance(window, dict) and window.get("direction") == "future" and requirement.get("requires_analysis") and not any(re.search(r"观察|若|如果|一旦|关注|验证(?:是否|能否)|触发|跟踪|\b(?:if|watch|monitor)\b", claim.text, re.IGNORECASE) for claim in claims):
            reasons.append("requirement_observation_conditions_missing")
        reasons = stable_unique(reasons)
        check = {
            "requirement_id": requirement_id, "task_id": result.task_id,
            "dimension": dimension, "description": requirement.get("description") or dimension,
            "status": "answered" if not reasons else "partial" if available_facts else "missing",
            "evidence_ids": [fact.source_id for fact in facts],
            "available_evidence_ids": [fact.source_id for fact in available_facts],
            "claim_ids": [claim.claim_id for claim in claims],
            "reason": ",".join(reasons) if reasons else None,
        }
        result.requirement_results.append(check)
        if components:
            check["answered_components"] = [component for component in components if component not in missing_components]
            check["missing_components"] = missing_components
        if window_coverage is not None:
            check["window_coverage"] = window_coverage
        if reasons:
            missing = {**check, "subject": subject or result.subject}
            if missing_components:
                labels = {"revenue": "收入", "net_income": "净利润", "cash_flow": "现金流"}
                missing["description"] = "、".join(labels.get(str(component), str(component)) for component in missing_components) + "的事实解释尚未完成"
            result.missing_requirements.append(missing)
    result.missing_requirements = stable_unique(result.missing_requirements)
    if result.missing_requirements and result.status == "answered":
        result.status = "partial"


__all__ = ["claim_has_reliable_sources", "disclosure_sections", "evaluate_answer_requirements", "evidence_is_document_index", "overall_conclusion_block_reasons"]
