"""请求理解的唯一出口：由已绑定的任务生成执行与展示共用的合同。"""
from __future__ import annotations

import re
import hashlib
import json
from copy import deepcopy
from datetime import datetime
from typing import Any

from backend.config.ticker_mapping import normalize_ticker
from backend.graph.request_frame import compile_request_frame, compile_request_frames
from backend.graph.request_constraints import conditional_impact
from backend.graph.intent_contract import MACRO_INDICATOR_KEYS, canonical_evidence_kinds, evidence_plan_for_kinds, legacy_operation_for_contract


_METRIC_CONTRACTS = {
    "quote": ("performance", ["price_snapshot"], "price"),
    "cumulative_return": ("performance", ["price_window"], "price"),
    "max_drawdown": ("risk_level", ["price_window"], "risk"),
    "volume_breakout": ("technical_quality", ["price_window"], "technical"),
    "business_model": ("business_model", ["company_profile", "filing_context"], "business"),
    "competition": ("competition", ["company_profile", "document_context"], "competition"),
    "fundamental_quality": ("fundamental_quality", ["fundamental_snapshot", "filing_context"], "fundamental"),
    "valuation_reasonableness": ("valuation_reasonableness", ["price_snapshot", "company_profile", "earnings_estimates", "filing_context"], "valuation"),
    "risk_level": ("risk_level", ["risk_profile"], "risk"),
    "news_catalysts": ("news_catalysts", ["news_context"], "news"),
    "macro_impact": ("macro_impact", ["macro_context"], "macro"),
    "technical_quality": ("technical_quality", ["technical_snapshot"], "technical"),
    **{metric: ("technical_quality", ["technical_snapshot"], "technical") for metric in (
        "rsi14", "macd", "support", "resistance", "support_resistance",
    )},
    "earnings_date": ("news_catalysts", ["event_calendar"], "catalyst"),
    "macro_data": ("macro_impact", ["macro_context"], "macro"),
    **{metric: ("macro_impact", ["macro_context"], "macro") for metric in MACRO_INDICATOR_KEYS},
    "dividend_announcement": ("news_catalysts", ["filing_context"], "filing"),
    "investment_attractiveness": ("investment_attractiveness", ["price_snapshot", "technical_snapshot", "news_context", "company_profile", "fundamental_snapshot", "risk_profile"], "investment_opinion"),
    "earnings_impact": ("earnings_impact", ["filing_context", "earnings_estimates", "price_snapshot", "news_context", "transcript_context", "risk_profile"], "earnings"),
    "earnings_performance": ("fundamental_quality", ["filing_context", "earnings_estimates", "fundamental_snapshot", "news_context", "transcript_context"], "earnings"),
    "trend_quality": ("trend_quality", ["price_snapshot", "technical_snapshot"], "trend"),
    "performance": ("performance", ["price_snapshot"], "price"),
    "holdings_ownership": ("holdings_ownership", ["holdings_ownership"], "holdings"),
    "external_impact": ("external_impact", ["price_snapshot", "news_context", "risk_profile"], "external_entity_impact"),
    "document_summary": ("document_context", ["document_context"], "document"),
    "document_question": ("document_context", ["document_context"], "document"),
    **{metric: ("fundamental_quality", ["capital_allocation"], "fundamental") for metric in (
        "operating_cash_flow", "capital_expenditure", "dividends_paid", "repurchases_paid",
        "capital_allocation_surplus", "shares_outstanding", "net_share_change", "dividend_coverage", "debt_burden", "free_cash_flow",
    )},
    **{metric: ("fundamental_quality", ["filing_context"], "fundamental") for metric in (
        "revenue", "net_income", "operating_income",
    )},
}

_DETERMINISTIC_MEASUREMENTS = {
    "quote", "cumulative_return", "max_drawdown", "volume_breakout", "operating_cash_flow",
    "capital_expenditure", "free_cash_flow", "dividends_paid", "repurchases_paid", "capital_allocation_surplus",
    "shares_outstanding", "net_share_change", "dividend_coverage", "debt_burden", "revenue", "net_income",
    "operating_income", "earnings_date", "dividend_announcement", "macro_data",
} | set(MACRO_INDICATOR_KEYS)
_DETERMINISTIC_MEASUREMENTS.update({"rsi14", "macd", "support", "resistance", "support_resistance"})
_QUALITATIVE_MEASUREMENTS = {
    "business_model", "competition", "fundamental_quality", "valuation_reasonableness", "risk_level",
    "earnings_impact", "earnings_performance", "investment_attractiveness", "macro_impact", "external_impact",
    "document_summary", "document_question",
}
_TECHNICAL_MEASUREMENTS = {"technical_quality", "trend_quality", "rsi14", "macd", "support", "resistance", "support_resistance"}

_COMMON_SOURCE_ATTRIBUTES = {"source_timestamp", "source_url", "unit", "frequency", "period_start", "period_end", "published_at"}
_METRIC_ATTRIBUTES = {
    "quote": {"currency", "source_timestamp", "market_session", "end_close", "price_basis"},
    "cumulative_return": {"currency", "source_timestamp", "price_basis", "dividends_included", "end_close", "base_close", "base_date", "end_date", "intervals"},
    "max_drawdown": {"currency", "source_timestamp", "price_basis", "peak_date", "peak_close", "trough_date", "trough_close"},
    "volume_breakout": {"currency", "source_timestamp", "price_basis", "confirmation_threshold", "range_start", "range_end"},
    **{metric: _COMMON_SOURCE_ATTRIBUTES | {"currency"} for metric in (
        "operating_cash_flow", "capital_expenditure", "free_cash_flow", "dividends_paid", "repurchases_paid", "capital_allocation_surplus", "debt_burden",
    )},
    **{metric: _COMMON_SOURCE_ATTRIBUTES | {"report_month", "observation_date", "source_updated_at"} for metric in ("macro_data", *MACRO_INDICATOR_KEYS)},
}
for _price_metric in ("quote", "cumulative_return", "max_drawdown", "volume_breakout"):
    _METRIC_ATTRIBUTES[_price_metric] |= _COMMON_SOURCE_ATTRIBUTES
# 报价、区间和技术指标由工具按标准定义计算；模型列出的价量原料不是独立采集项。
_TOOL_COMPUTED_MEASUREMENTS = {"quote", "cumulative_return", "max_drawdown", "volume_breakout"} | _TECHNICAL_MEASUREMENTS
# 模型偶尔把币种、时间等属性写进 components，这里归回属性。
_COMPONENT_ATTRIBUTES = {"currency": "currency", "quote_timestamp": "source_timestamp", "timestamp": "source_timestamp",
                         "source_timestamp": "source_timestamp", "after_hours_flag": "market_session",
                         "is_after_hours": "market_session", "market_session": "market_session",
                         "source": "source_url", "fiscal_period": "period_end"}
_REGISTERED_ATTRIBUTES = set().union(*_METRIC_ATTRIBUTES.values()) | {"data_frequency", "confirmation_status", "amount_per_share", "announced_at", "payable_date", "record_date"}


def _constraint_needs_analysis(requirement: dict[str, Any], local_constraints: list[dict[str, Any]], scope: dict[str, Any]) -> bool:
    controls = [item for item in local_constraints if item.get("source_text") == requirement.get("source_text")]
    if controls and all(item.get("constraint_type") in {"exclude_dimension", "exclude_comparison"}
                        or item.get("constraint_type") == "source_policy" and item.get("source_requirement") in {"primary", "attributed", "traceable"}
                        or item.get("dimension") in {"time_consistency", "period_alignment"} for item in controls):
        return False
    if scope.get("kind") in {"latest_quote", "trading_sessions"} and scope.get("selection") == "latest_complete" and scope.get("completed_only") is True:
        return False
    return True


def _attribute_scope_key(scope: dict[str, Any]) -> tuple[Any, ...]:
    """相同实际时间范围可共享属性，原文片段与交易日单位别名不影响归属。"""
    kind = scope.get("kind", "none")
    unit = scope.get("unit") if kind == "calendar_window" else None
    return tuple(scope.get(key) for key in ("kind", "selection", "count", "completed_only", "direction", "as_of", "period_start", "period_end")) + (unit,)


def _bind_attribute_requirements(requirements: list[dict[str, Any]], subjects: dict[str, dict[str, Any]]) -> None:
    def subject_key(row: dict[str, Any]) -> tuple[str, ...]:
        if row.get("subject"):
            return (row["subject"],)
        return tuple(sorted({token for ref in row.get("subject_refs", [])
                             for token in (subjects.get(ref, {}).get("tickers") or [f"ref:{ref}"])}))

    for requirement in requirements:
        attributes = set(requirement.get("attributes") or [])
        if (requirement.get("metric") != "unknown" or requirement.get("kind") != "fact_attribute"
                or requirement.get("components") or requirement.get("input_dependencies") or not attributes
                or requirement.get("measurement", "other") not in {"other", "", "date"}):
            continue
        owners: dict[tuple[str, tuple[Any, ...]], dict[str, Any]] = {}
        for candidate in requirements:
            metric = candidate.get("metric")
            if candidate.get("attribute_owner_requirement_id") or candidate.get("capability_status") != "supported" or not attributes <= _METRIC_ATTRIBUTES.get(metric, set()):
                continue
            if (subject_key(candidate) != subject_key(requirement)
                    or _attribute_scope_key(candidate.get("time_scope") or {}) != _attribute_scope_key(requirement.get("time_scope") or {})):
                continue
            owners.setdefault((metric, _attribute_scope_key(candidate.get("time_scope") or {})), candidate)
        if len(owners) != 1:
            continue
        owner = next(iter(owners.values()))
        requirement.update(raw_metric="unknown", metric=owner["metric"], dimension=owner["dimension"],
                           evidence_kinds=list(owner["evidence_kinds"]), capability_status="supported", requires_analysis=False,
                           attribute_owner_requirement_id=owner["requirement_id"])


def _scope_projection(scope: dict[str, Any]) -> dict[str, Any]:
    projected = dict(scope)
    if scope.get("kind") == "calendar_window" and scope.get("count"):
        count = int(scope["count"])
        unit = str(scope.get("unit") or "days").lower()
        if unit in {"event", "events"}:
            if scope.get("direction") == "future":
                projected["days_ahead"] = 120
            return projected
        hours = count * {"hours": 1, "hour": 1, "小时": 1, "days": 24, "day": 24, "天": 24,
                         "weeks": 168, "week": 168, "周": 168, "months": 720, "month": 720, "个月": 720,
                         "quarter": 2160, "quarters": 2160, "季度": 2160, "year": 8760, "years": 8760, "年": 8760}.get(unit, 24)
        if scope.get("direction") == "future":
            projected["days_ahead"] = hours / 24
        else:
            projected.update(hours_back=hours, max_age_hours=hours)
    return projected


def _bind_comparison_requirements(requirements: list[dict[str, Any]]) -> None:
    for requirement in requirements:
        multiple_subjects = len(set(requirement.get("subject_refs") or [])) > 1
        relational_explanation = requirement.get("kind") == "explanation" and multiple_subjects
        if requirement.get("kind") != "comparison" and not relational_explanation:
            continue
        components = requirement.get("components") or []
        metric = requirement.get("metric")
        relationship = metric == "comparison" or metric == "unknown" and (
            components and all(component in _METRIC_CONTRACTS for component in components)
            or relational_explanation and not components)
        related = [candidate for candidate in requirements if candidate is not requirement
            and candidate.get("kind") not in {"constraint", "input_dependency", "comparison"}
            and candidate.get("metric") in _METRIC_CONTRACTS
            and candidate.get("capability_status") in {"supported", "retrieval_required"}
            and set(candidate.get("subject_refs") or []).issubset(set(requirement.get("subject_refs") or []))
            and candidate.get("subject_refs")
            and (candidate.get("metric") in components if components else relationship or candidate.get("metric") == metric)]
        scope = requirement.get("time_scope") or {}
        if components and scope.get("kind") in {"fiscal_quarter", "fiscal_year"}:
            related = [candidate for candidate in related if (candidate.get("time_scope") or {}).get("kind") == scope["kind"]]
        if metric == "comparison" and not components and not related:
            raise ValueError("request_comparison_inputs_missing")
        if relational_explanation and metric == "unknown" and not components:
            bound_refs = {ref for candidate in related for ref in candidate.get("subject_refs", [])}
            relationship = set(requirement.get("subject_refs") or []).issubset(bound_refs)
            if not relationship:
                related = []
        if relationship and (components or related):
            requirement.update(raw_metric=metric, metric="comparison", dimension="comparison", capability_status="supported")
        if related:
            requirement["comparison_requirement_ids"] = [candidate["requirement_id"] for candidate in related]
            requirement["comparison_inputs"] = deepcopy(related)
        if related or relationship and components:
            requirement["evidence_kinds"] = list(dict.fromkeys([*requirement.get("evidence_kinds", []),
                *(kind for component in components for kind in _METRIC_CONTRACTS.get(component, ("", [], ""))[1]),
                *(kind for candidate in related for kind in candidate.get("evidence_kinds", []))]))


def _normalize_semantic_scope(scope: dict[str, Any], metric: str) -> dict[str, Any]:
    """按结构字段纠正词表漂移；latest 由服务端取当前时点，不接收模型造的日期。"""
    normalized = dict(scope)
    unit = str(scope.get("unit") or "").strip().lower()
    financial = "capital_allocation" in _METRIC_CONTRACTS.get(metric, ("", [], ""))[1] or metric in {"revenue", "net_income", "operating_income", "earnings_performance"}
    fiscal_kind = "fiscal_quarter" if unit in {"quarter", "quarters", "fiscal_quarter", "季度"} else "fiscal_year" if unit in {"year", "years", "fiscal_year", "财年", "年"} else None
    if financial and fiscal_kind:
        if scope.get("kind") in {"fiscal_quarter", "fiscal_year"} and scope["kind"] != fiscal_kind:
            raise ValueError("request_financial_period_conflict")
        normalized["kind"] = fiscal_kind
    elif metric in {"cumulative_return", "max_drawdown", "volume_breakout"} and unit in {"trading_sessions", "trading_session", "trading_days", "trading_day", "交易日"}:
        normalized["kind"] = "trading_sessions"
    elif metric == "quote" and (unit == "quote" or scope.get("kind") == "trading_sessions" and scope.get("count") == 1 and scope.get("selection") == "latest_complete"):
        normalized.update(kind="latest_quote", count=None, unit=None)
    elif metric in {"news_catalysts", "earnings_date"} and scope.get("direction") == "future" and fiscal_kind:
        normalized["kind"] = "calendar_window"
    if normalized.get("kind") in {"fiscal_quarter", "fiscal_year"}:
        if normalized.get("count") is None:
            normalized["count"] = 1
    as_of = normalized.get("as_of")
    if as_of:
        try:
            datetime.fromisoformat(str(as_of).replace("Z", "+00:00"))
        except ValueError:
            if normalized.get("selection") in {"latest", "latest_complete"}:
                normalized["as_of"] = None
            else:
                raise ValueError("request_as_of_invalid") from None
    for key in ("period_start", "period_end"):
        if normalized.get(key):
            try:
                datetime.fromisoformat(str(normalized[key]).replace("Z", "+00:00"))
            except ValueError:
                if normalized.get("selection") in {"latest", "latest_complete"}:
                    normalized[key] = None
                else:
                    raise ValueError("request_explicit_period_invalid") from None
    return normalized


def _missing_input_dependencies(raw: list[Any], query: str, result: dict[str, Any], context: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    from backend.graph.memory_scope import current_report_context

    valid_keys = {"analysis_subject", "previous_report", "source_document", "document_url", "report_text", "position_cost_basis", "portfolio_positions", "comparison_target", "other"}
    ui = context.get("ui_context") if isinstance(context.get("ui_context"), dict) else {}
    report = current_report_context(context.get("memory_context")) or {}
    report_content = any(isinstance(report.get(key), str) and report[key].strip() for key in ("markdown", "report_text", "content", "text"))
    selections = ui.get("selections") if isinstance(ui.get("selections"), list) else []
    bound_subject = result.get("subject") if isinstance(result.get("subject"), dict) else {}
    selections = [*selections, *[item for item in bound_subject.get("selection_payload", []) if isinstance(item, dict)]]
    bound_inputs = [task.get("operation", {}).get("params", {}) for task in result.get("tasks", []) if isinstance(task, dict) and isinstance(task.get("operation"), dict)]
    positions = ui.get("positions") or next((item.get("positions") for item in bound_inputs if item.get("positions")), None)
    availability = {
        "analysis_subject": bool(bound_subject.get("tickers")),
        "previous_report": report_content, "report_text": report_content,
        "source_document": any(any(item.get(key) for key in ("url", "content", "text")) for item in selections if isinstance(item, dict)) or any(item.get("url") or item.get("urls") for item in bound_inputs),
        "document_url": any(item.get("url") or item.get("urls") for item in bound_inputs) or any(item.get("url") for item in selections if isinstance(item, dict)),
        "portfolio_positions": bool(positions),
        "position_cost_basis": bool(isinstance(positions, list) and any(isinstance(item, dict) and any(isinstance(item.get(key), (int, float)) for key in ("cost_basis", "average_cost", "purchase_price")) for item in positions)),
        "comparison_target": len(bound_subject.get("tickers") or []) > 1,
        "other": False,
    }
    reference_ids = {key for key, available in availability.items() if available}
    if report_content:
        reference_ids.update({"current_report", "previous_report", "last_report"})
    if availability["analysis_subject"]:
        reference_ids.update({"resolved_subject", *[str(ticker) for ticker in bound_subject.get("tickers", [])]})
    reference_ids.update(str(report[key]) for key in ("id", "report_id", "url") if report_content and report.get(key))
    for selection in selections:
        if not isinstance(selection, dict):
            continue
        if selection.get("id"):
            reference_ids.update({str(selection["id"]), f"selection:{selection['id']}"})
        if selection.get("url"):
            reference_ids.add(str(selection["url"]))
    for item in bound_inputs:
        reference_ids.update(str(value) for value in [item.get("url"), *(item.get("urls") or [])] if value)
    missing, specs = [], []
    for item in raw:
        spec = dict(item) if isinstance(item, dict) else {"input_key": str(item), "source_text": "", "source_ref": None}
        key = str(spec.get("input_key") or "")
        if key not in valid_keys:
            raise ValueError("request_input_reference_invalid")
        if isinstance(item, dict) and (not spec.get("source_text") or spec["source_text"] not in query):
            raise ValueError("request_input_source_unbound")
        spec["available"] = bool(availability[key]) and (not spec.get("source_ref") or str(spec["source_ref"]) in reference_ids)
        specs.append(spec)
        if not spec["available"] and key not in missing:
            missing.append(key)
    return missing, specs


def _normalize_constraints(raw: list[dict[str, Any]], subjects: dict[str, dict[str, Any]], query: str) -> list[dict[str, Any]]:
    constraints = []
    for item in raw:
        constraint = deepcopy(item)
        refs = list(dict.fromkeys(constraint.get("subject_refs") or constraint.get("scope_refs") or []))
        if any(ref not in subjects for ref in refs):
            raise ValueError("request_constraint_subject_unbound")
        if not constraint.get("source_text") or constraint["source_text"] not in query:
            raise ValueError("request_constraint_source_unbound")
        constraint.pop("scope_refs", None)
        constraint["subject_refs"] = refs
        constraints.append(constraint)
    return constraints


def _scoped_constraints(constraints: list[dict[str, Any]], refs: list[str]) -> list[dict[str, Any]]:
    return [deepcopy(item) for item in constraints if not item.get("subject_refs") or set(item["subject_refs"]).intersection(refs)]


def deterministic_fallback_contract(result: dict[str, Any], diagnostics: dict[str, Any]) -> dict[str, Any]:
    """语义确认失败时沿用规则计划继续研究；结果质量会标注要求未确认，不能宣称完整回答。"""
    understanding = dict(result.get("understanding") or {})
    understanding.update(requirements_status="deterministic_fallback",
                         semantic_contract={"status": "unconfirmed", "tasks": [], "requirements": []})
    result["understanding"] = understanding
    result["trace"] = {**dict(result.get("trace") or {}), "request_requirements": diagnostics}
    if result.get("understanding_v2"):
        result["understanding_v2"] = {**dict(result["understanding_v2"]), "requirements_status": "deterministic_fallback"}
    return result


def compile_semantic_contract(result: dict[str, Any], semantic: dict[str, Any], diagnostics: dict[str, Any], *, input_context: dict[str, Any] | None = None) -> dict[str, Any]:
    """只验证语义抽取对象并投影，不能重新解析原文或裁剪原始要求。"""
    understanding = dict(result.get("understanding") or {})
    diagnostics = {**diagnostics, "raw_semantic": deepcopy(semantic)}
    query = str(understanding.get("original_query") or result.get("query") or "")
    mode = str(semantic.get("output_mode") or result.get("output_mode") or "chat")
    result["output_mode"] = mode
    subjects = [dict(item) for item in semantic.get("subjects", []) if isinstance(item, dict)]
    subject_map = {str(item.get("id")): item for item in subjects}
    if len(subject_map) != len(subjects) or any(not key or key == "None" for key in subject_map):
        raise ValueError("request_subject_ids_invalid")
    for subject in subjects:
        subject["tickers"] = list(dict.fromkeys(normalize_ticker(str(value)) for value in subject.get("tickers", []) if value))
        if subject.get("type") not in {"company", "macro", "theme", "portfolio", "research_doc", "filing", "news_item", "news_set", "index", "crypto", "fund", "commodity", "unknown"}:
            from backend.graph.intent.predicates import _subject_type_for_ticker
            subject["raw_type"] = subject.get("type")
            subject["type"] = _subject_type_for_ticker(subject["tickers"][0]) if subject["tickers"] else "unknown"
    if semantic.get("relation", "single") == "single":
        company_subjects = [subject for subject in subjects if subject.get("type") == "company" and subject.get("tickers")]
        tickers = {ticker for subject in company_subjects for ticker in subject["tickers"]}
        mentioned = {ticker for ticker in tickers if re.search(r"(?<![A-Za-z0-9])" + re.escape(ticker) + r"(?![A-Za-z0-9])", query, re.I)}
        if len(mentioned) == 1 and (len(tickers) > 1 or len(company_subjects) > 1):
            primary_labels = {str(subject.get("label") or "").casefold() for subject in company_subjects if mentioned.intersection(subject["tickers"])}
            additional_named = any(str(subject.get("label") or "").casefold() in query.casefold()
                and str(subject.get("label") or "").strip()
                and str(subject.get("label") or "").casefold() not in primary_labels
                for subject in company_subjects if not mentioned.intersection(subject["tickers"]))
            if not additional_named:
                raise ValueError("request_single_subject_expanded")
    declared_constraints = [item for item in semantic.get("constraints", []) if isinstance(item, dict)]
    declared_constraints.extend(item for row in semantic.get("requirements", []) for item in row.get("constraints", []) if isinstance(item, dict))
    normalized_constraints = _normalize_constraints(declared_constraints, subject_map, query)
    constraints = list({json.dumps(item, sort_keys=True, ensure_ascii=False): item for item in normalized_constraints}.values())
    requirements: list[dict[str, Any]] = []
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    seen_ids: set[str] = set()
    for raw in semantic.get("requirements", []):
        requirement = deepcopy(raw)
        local_constraints = _normalize_constraints(requirement.get("constraints") or [], subject_map, query)
        source = str(requirement.get("source_text") or "")
        start = query.find(source)
        if not source.strip() or start < 0:
            raise ValueError("request_requirement_source_unbound")
        if requirement.get("kind") == "constraint" and not local_constraints:
            local_constraints = [deepcopy(item) for item in constraints if item["source_text"] == source]
        refs = list(dict.fromkeys(str(ref) for ref in requirement.get("subject_refs", [])))
        if requirement.get("kind") == "constraint" and not refs:
            refs = list(dict.fromkeys(ref for item in local_constraints for ref in item.get("subject_refs", [])))
        if any(ref not in subject_map for ref in refs):
            raise ValueError("request_requirement_subject_unbound")
        ticker = normalize_ticker(str(requirement.get("subject") or "")) or None
        if ticker and refs and not any(ticker in subject_map[ref].get("tickers", []) for ref in refs):
            raise ValueError("request_requirement_ticker_unbound")
        if not refs and ticker:
            refs = [ref for ref, subject in subject_map.items() if ticker in subject.get("tickers", [])]
            if not refs:
                raise ValueError("request_requirement_ticker_unbound")
        applicable_refs = [ref for ref in refs if not ticker or ticker in subject_map[ref].get("tickers", [])]
        applied_constraints = _scoped_constraints([*constraints, *local_constraints], applicable_refs)
        exclusions = {str(item.get("dimension")) for item in applied_constraints if item.get("constraint_type") == "exclude_dimension"}
        metric = str(requirement.get("metric") or "unknown")
        calculation = requirement.get("calculation")
        if calculation is not None:
            from backend.graph.semantic_requirements import SemanticCalculation
            requirement["calculation"] = SemanticCalculation.model_validate(calculation).model_dump()
            if requirement.get("kind") not in {"calculation", "comparison"}:
                raise ValueError("request_calculation_kind_invalid")
        if metric == "rsi":
            requirement["raw_metric"] = metric
            metric = requirement["metric"] = "rsi14"
        if (requirement.get("kind") in {"fact_attribute", "calculation"}
                and metric == "unknown" and requirement.get("measurement") == "price"
                and requirement.get("price_role") in {"current", "window_end", "latest_completed_close"}):
            requirement["raw_metric"] = metric
            metric = requirement["metric"] = "quote"
        if requirement.get("kind") == "event_window" and metric == "unknown":
            # 事件窗口本身就是事件/催化查询；未知指标名不应让整项失去取数计划。
            requirement["raw_metric"] = metric
            metric = requirement["metric"] = "news_catalysts"
        if calculation is not None and metric in _TOOL_COMPUTED_MEASUREMENTS:
            raise ValueError("request_calculation_domain_conflict")
        definition = _METRIC_CONTRACTS.get(metric)
        is_constraint = requirement.get("kind") == "constraint"
        supplied_evidence = list(requirement.get("evidence_kinds") or [])
        evidence = canonical_evidence_kinds(supplied_evidence)
        unknown_evidence = [kind for kind in supplied_evidence if kind not in evidence]
        if is_constraint:
            matching_controls = [item for item in [*constraints, *local_constraints]
                if item.get("source_text") and item["source_text"] in source
                and (not item.get("subject_refs") or set(item["subject_refs"]).issubset(set(refs)))]
            if definition and definition[1] and not matching_controls:
                raise ValueError("request_constraint_metric_conflict")
            evidence = []
            requirement["capability_status"] = "supported"
            local_types = {item.get("constraint_type") for item in local_constraints}
            requirement["constraint_type"] = next(iter(local_types)) if len(local_types) == 1 else "other"
            source_levels = {item.get("source_requirement", "unspecified") for item in local_constraints}
            if len(source_levels) == 1:
                requirement["source_requirement"] = next(iter(source_levels))
        elif definition:
            evidence = list(dict.fromkeys([*definition[1], *evidence]))
            requirement["raw_dimension"] = requirement.get("dimension")
            requirement["dimension"] = definition[0]
            requirement["raw_capability_status"] = requirement.get("capability_status")
            requirement["capability_status"] = "supported"
            market = "HK" if ticker and ticker.endswith(".HK") else "CN" if ticker and ticker.endswith((".SS", ".SZ", ".BJ")) else "US"
            if market in {"CN", "HK"} and metric in {"revenue", "net_income", "operating_income"}:
                evidence = list(dict.fromkeys([*evidence, "fundamental_snapshot"]))
            if not evidence_plan_for_kinds(evidence, market=market):
                requirement["capability_status"] = "retrieval_required"
                requirement["capability_reason"] = "structured_source_unavailable_for_market"
                evidence = ["filing_context", "document_context"]
            if (not ticker and not any(subject_map[ref].get("tickers") for ref in refs)
                    and any(subject_map[ref].get("type") == "company" and subject_map[ref].get("label") for ref in refs)):
                requirement["capability_status"] = "retrieval_required"
                requirement["capability_reason"] = "security_identifier_pending"
                evidence = ["document_context"]
        elif requirement.get("kind") == "comparison" and metric == "comparison":
            requirement.update(dimension="comparison", capability_status="supported")
        elif not is_constraint:
            requirement.update(metric_text=str(requirement.get("metric_text") or metric), metric="unknown", capability_status="unsupported")
        if unknown_evidence:
            requirement["unmapped_evidence_kinds"] = unknown_evidence
        input_dependencies, input_specs = _missing_input_dependencies(requirement.get("input_dependencies") or [], query, result, input_context or {})
        requirement["input_dependencies"] = input_dependencies
        if input_specs:
            requirement["input_dependency_specs"] = input_specs
        if input_dependencies:
            requirement["capability_status"] = "input_missing"
        if not is_constraint and requirement.get("dimension") in exclusions:
            raise ValueError("request_requirement_exclusion_conflict")
        raw_scope = dict(requirement.get("time_scope") or {"kind": "none"})
        scope = _normalize_semantic_scope(raw_scope, metric)
        frequency_aliases = {"daily": "daily", "1d": "daily", "weekly": "weekly", "1wk": "weekly", "monthly": "monthly", "1mo": "monthly"}
        presentation = list(requirement.get("presentation") or [])
        from backend.graph.semantic_requirements import PRESENTATION_FIELDS
        if any(item not in PRESENTATION_FIELDS for item in presentation):
            raise ValueError("request_presentation_invalid")
        attributes = []
        for attribute in requirement.get("attributes") or []:
            if attribute in PRESENTATION_FIELDS:
                presentation.append(attribute)
                continue
            raw_attribute = str(attribute).strip()
            if raw_attribute.startswith("timeframe:") and raw_attribute.partition(":")[2] in frequency_aliases:
                requirement["data_frequency"] = frequency_aliases[raw_attribute.partition(":")[2]]
                continue
            normalized_attribute = raw_attribute.strip(":`\"' ")
            key, separator, value = normalized_attribute.partition(":")
            if separator and key.strip() in _REGISTERED_ATTRIBUTES:
                # 模型偶尔输出 confirmation_status:confirmed 之类键值；属性只保留注册键，取值由证据核对。
                normalized_attribute = key.strip()
                if normalized_attribute == "data_frequency" and value.strip() in frequency_aliases:
                    requirement["data_frequency"] = frequency_aliases[value.strip()]
            if not normalized_attribute or normalized_attribute == "data_frequency":
                continue
            attributes.append(normalized_attribute if normalized_attribute in _REGISTERED_ATTRIBUTES else raw_attribute)
        components = []
        from backend.graph.semantic_requirements import ExtractedRequirement
        for component in requirement.get("components") or []:
            if (not isinstance(component, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", component)
                    or component in ExtractedRequirement.model_fields or component in {"value", "operation", "baseline"}):
                raise ValueError("request_component_shape_invalid")
            name = str(component).strip()
            if name in _METRIC_CONTRACTS and name not in _DETERMINISTIC_MEASUREMENTS:
                raise ValueError("request_component_qualitative_invalid")
            if name in _COMPONENT_ATTRIBUTES:
                attributes.append(_COMPONENT_ATTRIBUTES[name])
            elif name and metric not in _TOOL_COMPUTED_MEASUREMENTS:
                components.append(name)
        requirement["components"] = components
        requirement["presentation"] = list(dict.fromkeys(presentation))
        if set(presentation) & {"include_inputs", "include_formula"} and not requirement.get("calculation") and metric not in {"cumulative_return", "max_drawdown", "volume_breakout"}:
            raise ValueError("request_calculation_presentation_domain_conflict")
        requirement["attributes"] = attributes
        if metric in {"quote", "news_catalysts", "earnings_date"}:
            # 即时/收盘报价没有采样频率可言，日线措辞不应变成需要核对的频率要求。
            requirement["data_frequency"] = "unspecified"
        if metric in _TECHNICAL_MEASUREMENTS or is_constraint and scope.get("kind") == "trading_sessions" and scope.get("count") is None:
            frequency = requirement.get("data_frequency", "unspecified")
            if frequency == "unspecified" and scope.get("unit") in {"trading_day", "trading_days", "daily", "1d"}:
                requirement["data_frequency"] = "daily"
            if scope.get("kind") == "trading_sessions" and scope.get("count") is None:
                scope.update(kind="none", unit=None)
            elif metric in _TECHNICAL_MEASUREMENTS and scope.get("kind") == "latest_quote":
                scope.update(kind="none", unit=None)
        if metric == "quote" and requirement.get("price_role") in {"window_end", "latest_completed_close"}:
            scope.update(kind="latest_quote", count=None, unit=None)
        if scope != raw_scope:
            requirement["raw_time_scope"] = raw_scope
        if metric == "news_catalysts" and scope.get("direction") == "future":
            evidence = list(dict.fromkeys([*evidence, "event_calendar"]))
        if scope.get("source_text") and scope["source_text"] not in query:
            raise ValueError("request_time_scope_source_unbound")
        if scope.get("count") is not None and (not isinstance(scope["count"], int) or scope["count"] <= 0):
            raise ValueError("request_time_scope_count_invalid")
        if scope.get("kind") == "trading_sessions" and (not isinstance(scope.get("count"), int) or scope["count"] <= 0):
            raise ValueError("request_trading_window_invalid")
        if (scope.get("kind") == "trading_sessions" and scope["count"] > 252
                or "capital_allocation" in evidence and (scope.get("count") or 1) > 8):
            requirement.update(capability_status="unsupported", unsupported_reason="scope_exceeds_capability")
        attribute_aliases = {"currency_unit": "currency", "timestamp": "source_timestamp", "quote_timestamp": "source_timestamp",
                             "source": "source_url", "fiscal_period": "period_end",
                             "closing_price": "end_close", "close_price": "end_close", "dividend_included": "dividends_included",
                             "is_after_hours": "market_session", "after_hours": "market_session"}
        requirement["attributes"] = list(dict.fromkeys(attribute_aliases.get(str(attribute), str(attribute)) for attribute in requirement.get("attributes", [])))
        if metric == "quote":
            requirement["attributes"] = list(dict.fromkeys([*requirement["attributes"], "currency", "source_timestamp"]))
        elif metric == "cumulative_return":
            requirement["attributes"] = list(dict.fromkeys([*requirement["attributes"], "price_basis", "dividends_included"]))
        if metric == "quote" and requirement.get("price_role") == "window_end":
            requirement["attributes"] = list(dict.fromkeys([*requirement["attributes"], "end_close"]))
        requires_analysis = bool(requirement.get("requires_analysis") or requirement.get("kind") == "explanation")
        if requirement.get("kind") == "constraint":
            requires_analysis = _constraint_needs_analysis(requirement, local_constraints, scope)
        elif metric in _QUALITATIVE_MEASUREMENTS:
            requires_analysis = True
        elif metric in _DETERMINISTIC_MEASUREMENTS and requirement.get("kind") in {"fact_attribute", "calculation"}:
            if requires_analysis:
                requirement["raw_requires_analysis"] = True
            requires_analysis = False
        requirement.update(source_span={"start": start, "end": start + len(source)}, subject=ticker, subject_refs=refs,
                           evidence_kinds=evidence, time_scope=scope, requires_explicit_binding=True,
                           requires_analysis=requires_analysis,
                           constraints=applied_constraints)
        identity = {key: requirement.get(key) for key in ("source_text", "subject_refs", "subject", "metric", "kind", "time_scope", "components", "attributes", "calculation", "presentation")}
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
        requirement_id = f"requirement:{digest}"
        if requirement_id in seen_ids:
            raise ValueError("duplicate_semantic_requirement")
        seen_ids.add(requirement_id)
        requirement["requirement_id"] = requirement_id
        requirements.append(requirement)
        groups.setdefault(tuple(refs), []).append(requirement)
    if not requirements:
        raise ValueError("request_requirements_empty")
    _bind_attribute_requirements(requirements, subject_map)
    _bind_comparison_requirements(requirements)
    for requirement in requirements:
        if (requirement.get("metric") == "quote" and requirement.get("time_scope", {}).get("kind") == "latest_quote"
                and requirement.get("time_scope", {}).get("selection") == "latest_complete"
                and any("price_window" in candidate.get("evidence_kinds", []) and candidate.get("subject_refs") == requirement.get("subject_refs")
                        and candidate.get("time_scope", {}).get("completed_only") for candidate in requirements)):
            requirement["evidence_kinds"] = ["price_window"]
    # 全局约束与当前首个主体共享执行边界，不派生额外空任务。
    if () in groups and len(groups) > 1 and all(row.get("kind") == "constraint" for row in groups[()]):
        global_rows = groups.pop(())
        groups[next(iter(groups))].extend(global_rows)
    ready, blocked, frames = [], [], []
    bound_tasks = [task for task in result.get("tasks", []) if isinstance(task, dict)]
    relation = str(semantic.get("relation") or "single")
    seed_tasks: list[dict[str, Any]] | None = None
    for index, (refs, rows) in enumerate(groups.items(), 1):
        group_subjects = [subject_map[ref] for ref in refs]
        tickers = list(dict.fromkeys(ticker for item in group_subjects for ticker in item.get("tickers", [])))
        subject_type = str((group_subjects[0] if group_subjects else {}).get("type") or "unknown")
        label = "、".join(str(item.get("label") or "") for item in group_subjects) or "研究要求"
        named_company = subject_type == "company" and any(str(item.get("label") or "").strip() for item in group_subjects)
        task_constraints = _scoped_constraints(constraints, list(refs))
        exclusions = {str(item.get("dimension")) for item in task_constraints if item.get("constraint_type") == "exclude_dimension"}
        task_id, frame_id = f"task_{index}", f"request_task_{index}"
        evidence = list(dict.fromkeys(kind for row in rows if row.get("capability_status") in {"supported", "retrieval_required"}
                                     for kind in row.get("evidence_kinds", [])))
        if any(row.get("capability_status") == "unsupported" and row.get("kind") != "constraint" for row in rows):
            # 以已确认的主体和原文检索，不再依赖旧规则能否认识该公司。
            excluded_kinds = {kind for definition in _METRIC_CONTRACTS.values() if definition[0] in exclusions for kind in definition[1]}
            unmapped_research = any(row.get("capability_status") == "unsupported"
                and (row.get("requires_analysis") or row.get("kind") in {"explanation", "comparison"}) for row in rows)
            if unmapped_research and seed_tasks is None:
                seed_tasks = finalize_request_contract(deepcopy(result)).get("tasks", [])
            seeded_evidence = [kind for seed in seed_tasks or [] if unmapped_research and set(seed.get("tickers") or []) == set(tickers)
                               for kind in seed.get("required_evidence") or []]
            discovery = ["document_context", *seeded_evidence]
            if unmapped_research and not seeded_evidence and subject_type == "company":
                discovery.extend(["company_profile", "filing_context"])
            evidence = list(dict.fromkeys([*evidence, *(kind for kind in discovery if kind not in excluded_kinds)]))
        if named_company and not tickers:
            evidence = ["document_context"]
        facets = list(dict.fromkeys(_METRIC_CONTRACTS[row["metric"]][2] for row in rows if row.get("metric") in _METRIC_CONTRACTS and row.get("kind") != "constraint"))
        if any(row.get("metric") == "news_catalysts" and "event_calendar" in row.get("evidence_kinds", []) for row in rows):
            facets = ["catalyst" if facet == "news" else facet for facet in facets]
        if any(row.get("metric") == "earnings_impact" for row in rows) and "price" not in facets:
            facets.append("price")
        dimensions = list(dict.fromkeys(row.get("dimension") for row in rows if row.get("kind") != "constraint"))
        shape = "compare" if relation in {"compare", "rank"} and len(tickers) > 1 else "answer"
        render = {"shape": shape, "dimensions": dimensions, "answer_requirements": rows}
        contract = {"version": "intent_contract.v2", "contract_id": f"contract_{frame_id}", "frame_id": frame_id,
                    "subject_type": subject_type, "target_scope": "multi" if len(tickers) > 1 else "single" if tickers else "unknown",
                    "primary_tickers": tickers, "facets": facets, "per_ticker_required": shape == "compare",
                    "render_intent": render, "required_evidence": evidence, "evidence_plan": evidence_plan_for_kinds(evidence),
                    "budget_profile": "semantic_requirements", "source": "confirmed_semantic_requirements"}
        operation = legacy_operation_for_contract(contract, subject_type=subject_type)
        active_rows = [row for row in rows if row.get("kind") not in {"constraint", "input_dependency"}]
        if shape != "compare" and active_rows and all(row.get("kind") in {"fact_attribute", "calculation"} and not row.get("requires_analysis") for row in active_rows):
            operation["name"] = "qa"
        operation["params"]["budget_profile"] = "semantic_requirements"
        if shape == "compare" and "performance_comparison" not in evidence:
            operation["params"].update(synthesis_only=True, data_profile="research_synthesis")
        scopes = [_scope_projection(row["time_scope"]) for row in rows if row.get("time_scope", {}).get("kind") != "none"]
        time_scope = next((scope for scope in scopes if scope.get("kind") == "calendar_window"), scopes[0] if scopes else {})
        task_text = query if len(groups) == 1 else "；".join(dict.fromkeys(row["source_text"] for row in rows))
        task = {"id": task_id, "title": label, "subject_type": subject_type, "subject_label": label, "tickers": tickers,
                "operation": operation, "request_text": task_text, "priority": 50, "order_index": index - 1,
                "request_frame_id": frame_id, "render_kind": "compare" if shape == "compare" else "single",
                "render_group_id": frame_id, "answer_requirements": rows, "required_evidence": evidence,
                "time_scope": time_scope, "constraints": task_constraints, "requirements_status": "confirmed"}
        bound = next((seed for seed in bound_tasks if seed.get("subject_type") == subject_type
                      and (not tickers or set(tickers) == set(seed.get("tickers") or []))), None)
        if bound:
            seed_operation = bound.get("operation") if isinstance(bound.get("operation"), dict) else {}
            seed_params = seed_operation.get("params") if isinstance(seed_operation.get("params"), dict) else {}
            # 仅保留已经由主体绑定器确认的外部输入，不复用旧意图/维度。
            for key in ("url", "urls", "source_ref", "source_refs", "holder", "positions"):
                if key in seed_params:
                    operation["params"][key] = deepcopy(seed_params[key])
            for key in ("selection_ids", "selection_types", "selection_payload"):
                if key in bound:
                    task[key] = deepcopy(bound[key])
            if subject_type in {"filing", "research_doc", "news_item", "news_set"}:
                operation["name"] = str(seed_operation.get("name") or "qa")
        missing_subject = not group_subjects or (subject_type in {"company", "index", "fund", "crypto", "commodity", "unknown"}
                                                and not tickers and not named_company)
        missing_input = bool(rows) and all(row.get("input_dependencies") or row.get("kind") == "constraint" for row in rows)
        if missing_subject or missing_input:
            reason = "task_missing_subject" if missing_subject else "task_missing_input"
            question = "请补充需要研究的股票代码或明确主题。"
            if any(row.get("input_dependencies") for row in rows):
                question = "请补充分析对象及本次任务需要的原始资料，例如上一份报告正文或可读取的链接。" if missing_subject else "请补充本次任务需要的原始资料，例如上一份报告正文或可读取的链接。"
            task.update(status="blocked", reason=reason, error_code=reason, question=question, fallback_allowed=False)
            blocked.append(task)
        else:
            ready.append(task)
        frames.append({"version": "request_frame.v2", "frame_id": frame_id, "query_text": task_text,
                       "subject": {"type": subject_type, "tickers": tickers, "label": label}, "task_ids": [task_id],
                       "lane": "clarify" if missing_subject or missing_input else "report" if mode == "investment_report" else "research",
                       "relation": relation, "time_scope": time_scope, "excluded_facets": sorted(exclusions),
                       "evidence_obligations": evidence, "render_contract": render, "intent_contract": contract,
                       "legacy_operation": operation, "source": "confirmed_semantic_requirements"})
    snapshot = {"version": "semantic_requirements.v1", "status": "confirmed", "query": query, "subjects": subjects, "output_mode": mode,
                "relation": relation, "requirements": deepcopy(requirements), "constraints": deepcopy(constraints),
                "tasks": deepcopy([*ready, *blocked])}
    understanding.update(route="research" if ready else "clarify", tasks=ready, blocked_tasks=blocked,
                         request_frames=frames, requirements_status="confirmed", semantic_contract=snapshot,
                         user_visible_summary=f"已保留 {len(requirements)} 项原始要求；可执行任务 {len(ready)} 项，待补充输入 {len(blocked)} 项。")
    contracts = [frame["intent_contract"] for frame in frames]
    trace = {**dict(result.get("trace") or {}), "understanding": understanding, "request_requirements": diagnostics,
             "semantic_contract": deepcopy(snapshot), "request_frames": frames, "intent_contracts": contracts,
             "request_compiler": {"version": "request_compiler.v2", "requirement_count": len(requirements), "task_count": len(ready)}}
    result.update(understanding=understanding, tasks=ready, blocked_tasks=blocked, request_frames=frames,
                  intent_contracts=contracts, trace=trace, chat_responded=False)
    result.pop("messages", None)
    if frames:
        result["request_frame"] = understanding["request_frame"] = trace["request_frame"] = frames[0]
        result["intent_contract"] = trace["intent_contract"] = contracts[0]
    if ready:
        result["operation"] = ready[0]["operation"]
        result["subject"] = {**dict(result.get("subject") or {}), "subject_type": ready[0]["subject_type"],
                             "tickers": list(dict.fromkeys(ticker for task in ready for ticker in task["tickers"]))}
        result["clarify"] = {"needed": False, "reason": "", "question": "", "suggestions": []}
        artifacts = dict(result.get("artifacts") or {})
        for key in ("draft_markdown", "direct_answer_request", "chat_responded"):
            artifacts.pop(key, None)
        result["artifacts"] = artifacts
    else:
        question = blocked[0]["question"]
        result["clarify"] = {"needed": True, "reason": blocked[0]["reason"], "question": question, "suggestions": []}
        result["artifacts"] = {**dict(result.get("artifacts") or {}), "draft_markdown": question}
    from backend.graph.request_task_contract import build_reply_contract
    previous_reply = result.get("reply_contract") or {}
    reply = build_reply_contract(query=query, output_mode=mode, tasks=ready, blocked_tasks=blocked,
                                 memory_context=(input_context or {}).get("memory_context"))
    for key in ("context_binding", "continuation_target"):
        if previous_reply.get(key):
            reply[key] = deepcopy(previous_reply[key])
    result["reply_contract"] = trace["reply_contract"] = reply
    if result.get("understanding_v2"):
        from backend.graph.understanding_v2 import _task_to_v2, build_subject_specs, chat_multi_ticker_research_limit

        all_tickers = list(dict.fromkeys(ticker for subject in subjects for ticker in subject.get("tickers", [])))
        projected_subjects = build_subject_specs(all_tickers)
        facets = list(dict.fromkeys(facet for contract in contracts for facet in contract["facets"]))
        v2 = {**dict(result["understanding_v2"]), "route": understanding["route"],
              "subjects": projected_subjects, "tasks": [_task_to_v2(task) for task in ready], "blocked_tasks": deepcopy(blocked),
              "scope": {"primary_tickers": all_tickers, "omitted_tickers": [], "max_chat_research_tickers": chat_multi_ticker_research_limit()},
              "facets": [{"id": f"facet_{name}", "name": name, "required": True} for name in facets],
              "relations": [{"id": "rel_compare_1", "type": relation,
                  "subject_ids": [subject["id"] for subject in projected_subjects], "facet_refs": facets}]
                  if relation in {"compare", "rank"} else [],
              "evidence_requirements": [{"task_id": task["id"], "profile": "semantic_requirements",
                  "required_evidence": list(task["required_evidence"]), "answer_requirements": deepcopy(task["answer_requirements"])} for task in ready],
              "semantic_contract": deepcopy(snapshot), "requirements_status": "confirmed",
              "provenance": [{"source": "request_compiler", "method": "confirmed_semantic_requirements"}],
              "legacy_projection": {"subject": result.get("subject"), "operation": result.get("operation"), "reply_contract": result.get("reply_contract")}}
        result["understanding_v2"] = understanding["v2"] = trace["understanding_v2"] = v2
    return result


def finalize_request_contract(result: dict[str, Any]) -> dict[str, Any]:
    understanding = dict(result.get("understanding") or {})
    ready = [dict(item) for item in result.get("tasks", understanding.get("tasks", [])) if isinstance(item, dict)]
    blocked = [dict(item) for item in result.get("blocked_tasks", understanding.get("blocked_tasks", [])) if isinstance(item, dict)]
    if not ready and not blocked:
        return result
    query = str(understanding.get("original_query") or result.get("query") or "")
    # 同一条件传导链不能拆成失去前提的两次宏观分析；独立公司任务保持各自边界。
    chain = [task for task in ready if task.get('subject_type') in {'macro','commodity','index'}]
    if len(chain) > 1 and conditional_impact(query) and not re.search(r'另外|另一个问题|\bseparately\b', query, re.I):
        lead = chain[0]
        lead['request_text'] = query
        lead['conditional_impact'] = True
        lead['tickers'] = list(dict.fromkeys(ticker for task in chain for ticker in task.get('tickers', [])))
        ready = [task for task in ready if task is lead or task not in chain]
    mode = str(result.get("output_mode") or "chat")
    all_tickers = list(dict.fromkeys(
        normalize_ticker(str(ticker)) for task in ready for ticker in task.get("tickers", [])
        if normalize_ticker(str(ticker))
    ))
    fragments = compile_request_frames(query=query, tickers=all_tickers, output_mode=mode)
    frames: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for order, task in enumerate([*ready, *blocked]):
        task_id = str(task.get("id") or f"task_{order + 1}")
        if task_id in seen_ids:
            raise ValueError("duplicate_request_task_id")
        seen_ids.add(task_id)
        tickers = list(dict.fromkeys(normalize_ticker(str(value)) for value in task.get("tickers", []) if value))
        subject_type = str(task.get("subject_type") or "unknown")
        previous = task.get("operation") if isinstance(task.get("operation"), dict) else {"name": str(task.get("operation") or "qa")}
        name = str(previous.get("name") or "qa")
        params = dict(previous.get("params") or {})
        scoped_query = str(task.get("request_text") or query)
        # 分句仅由 request_frame 编译器解释；不按相似度猜测任务身份。
        if len(all_tickers) > 1 and len(tickers) == 1 and name != "compare":
            candidates = [frame for frame in fragments if set(frame.get("subject", {}).get("tickers", [])) == set(tickers)]
            matching = [frame for frame in candidates if frame.get("legacy_operation", {}).get("name") == name]
            candidates = matching or candidates
            if candidates:
                scoped_query = "；".join(str(frame["query_text"]) for frame in candidates)
        elif subject_type == "macro" and not task.get('conditional_impact'):
            candidates = [frame for frame in fragments if frame.get("subject", {}).get("type") == "macro"]
            if candidates:
                scoped_query = "；".join(str(frame["query_text"]) for frame in candidates)
        frame_id = f"request_{task_id}"
        domain = {"price": "quote", "fetch": "news", "technical": "technical", "macro_brief": "macro"}.get(name, "")
        if subject_type == "macro":
            domain = "macro"
        frame = compile_request_frame(query=scoped_query, tickers=tickers, output_mode=mode,
            comparison_requested=name == "compare", domain_intent=domain,
            subject_type=subject_type, frame_id=frame_id)
        frame["task_ids"] = [task_id]
        frame["subject"]["label"] = str(task.get("subject_label") or ", ".join(tickers) or subject_type)
        contract = frame["intent_contract"]
        if task.get("reason") == "intent_contract_per_ticker_evidence":
            parent = next((item for item in frames if item["render_contract"].get("shape") == "compare"
                           and set(tickers) <= set(item["subject"].get("tickers", []))), None)
            if parent:
                for key in ("required_evidence", "facets", "budget_profile", "evidence_plan"):
                    contract[key] = parent["intent_contract"][key]
                frame["evidence_obligations"] = list(contract["required_evidence"])
                # 比较的逐标的任务仅准备事实；双方解释由父任务一次完成。
                task["evidence_support_for"] = parent["task_ids"][0]
                frame["evidence_support_for"] = parent["task_ids"][0]
                for requirement in frame["render_contract"].get("answer_requirements") or []:
                    requirement["requires_analysis"] = False
                    requirement["kind"] = "fact_attribute"
        projection = dict(frame["legacy_operation"])
        # 文档/持仓及估值计算是显式工作流变体，其证据仍由同一 frame 管理。
        if name in {"holdings", "valuation_sanity"} or subject_type in {"filing", "research_doc", "news_item", "news_set", "portfolio"}:
            projection["name"] = name
            frame["render_contract"]["variant"] = name
        projection["params"] = {**params, **dict(projection.get("params") or {}),
            "required_evidence": list(frame["evidence_obligations"]),
            "facets": list(contract.get("facets") or []), "intent_contract_id": contract["contract_id"],
            "budget_profile": contract.get("budget_profile", "default")}
        projection.setdefault("confidence", previous.get("confidence", 0.75))
        frame["legacy_operation"] = projection
        render_kind = "compare" if frame["render_contract"].get("shape") == "compare" else "single"
        task.update(id=task_id, tickers=tickers, request_text=scoped_query, operation=projection,
            title=str(task.get("title") or frame["subject"]["label"]),
            subject_label=frame["subject"]["label"], order_index=order, request_frame_id=frame_id,
            render_kind=render_kind, render_group_id=frame_id,
            answer_requirements=list(frame["render_contract"].get("answer_requirements") or []),
            required_evidence=list(frame["evidence_obligations"]))
        if frame.get("time_scope"):
            task["time_scope"] = dict(frame["time_scope"])
        task["priority"] = max(0, int(task.get("priority", 50)))
        if order >= len(ready):
            frame["lane"] = "clarify"
            task.setdefault("error_code", str(task.get("reason") or "task_blocked"))
        frames.append(frame)
    contracts = [frame["intent_contract"] for frame in frames]
    understanding.update(tasks=ready, blocked_tasks=blocked, request_frames=frames)
    trace = dict(result.get("trace") or {})
    trace.update(request_frames=frames, intent_contracts=contracts,
        request_compiler={"version": "request_compiler.v1", "task_count": len(ready), "blocked_count": len(blocked)})
    result.update(understanding=understanding, tasks=ready, blocked_tasks=blocked,
        request_frames=frames, intent_contracts=contracts, trace=trace)
    if frames:
        result["request_frame"] = understanding["request_frame"] = trace["request_frame"] = frames[0]
        result["intent_contract"] = trace["intent_contract"] = contracts[0]
    if ready:
        result["operation"] = ready[0]["operation"]
    return result
