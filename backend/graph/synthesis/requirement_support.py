"""精确指标和期间的证据核验，不以宽泛的同类资料代替用户要求。"""
from __future__ import annotations

import math
from datetime import date
from urllib.parse import urlsplit
from typing import Any


PRICE_METRICS = {"cumulative_return", "max_drawdown", "volume_breakout"}
MACRO_METRICS = {"nonfarm_payroll_change", "unemployment", "cpi", "fed_rate", "gdp_growth", "treasury_10y", "yield_spread"}
TECHNICAL_METRICS = {"rsi14", "macd", "support", "resistance", "support_resistance"}
from backend.graph.research_capabilities import FINANCIAL_METRICS
_ALIASES = {
    "cash_flow": ("operating_cash_flow", "free_cash_flow"),
    "capital_expenditure": ("capital_expenditure", "capex"),
    "net_share_change": ("net_share_change", "net_change"),
    "shares_outstanding": ("shares_outstanding", "end_shares"),
    "unemployment_rate": ("unemployment",),
    "rsi14": ("rsi14", "rsi"),
}


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def payload_for(evidence) -> dict:
    return {**evidence.metadata, **evidence.structured_data}


def metric_record(evidence, metric: str) -> dict | None:
    """仅认结构化值；标题、概述和加权平均股数不能替代实际指标。"""
    payload = payload_for(evidence)
    if metric == "earnings_estimates":
        for row in payload.get("earnings_estimate") or []:
            if isinstance(row, dict) and row.get("period") and _number(row.get("avg")):
                return {**row, "value": row["avg"], "forecast_period": row["period"]}
        return None
    if metric == "dividend_announcement":
        for row in payload.get("dividend_announcements") or []:
            if isinstance(row, dict) and row.get("content_read") is True and row.get("verification") == "official_filing_body" and _number(row.get("amount_per_share")) and row.get("source_url"):
                return row
        return None
    containers = [payload]
    containers.extend(payload[key] for key in ("metrics", "facts", "share_count") if isinstance(payload.get(key), dict))
    aliases = _ALIASES.get(metric, (metric,))
    for container in containers:
        for key in aliases:
            value = container.get(key)
            if isinstance(value, dict):
                if value.get("error") or value.get("status") in {"missing", "unavailable", "error"}:
                    continue
                if _number(value.get("value")):
                    return value
                if metric == "volume_breakout" and any(isinstance(value.get(flag), bool) for flag in ("breakout", "confirmed", "is_breakout")):
                    return value
                if metric == "debt_burden":
                    components = value.get("components") or {}
                    rows = [components.get(key) for key in ("debt_current", "debt_noncurrent", "cash_and_equivalents")]
                    if all(isinstance(row, dict) and _number(row.get("value")) and row.get("period_end") and row.get("unit") for row in rows):
                        if len({(row["period_end"], row["unit"]) for row in rows}) == 1:
                            return value
            elif _number(value):
                return {"value": value}
    if evidence.metric in aliases and _number(payload.get("value")):
        return payload
    # CompanyFacts 旧合同以并列数组保存值和期间，选择首个具备完整元数据的值。
    metadata = payload.get("fact_metadata") or {}
    for key in aliases:
        values, rows = payload.get(key), metadata.get(key)
        if isinstance(values, list) and isinstance(rows, list):
            for value, row in zip(values, rows):
                if (_number(value) and isinstance(row, dict) and row.get("period_end")
                        and (not payload.get("selected_period") or row["period_end"] == payload["selected_period"])):
                    return {**row, "value": value}
    return None


def metric_supports(evidence, metric: str) -> bool:
    if metric == "quote":
        payload = payload_for(evidence)
        return evidence.kind in {"price_snapshot", "price_window"} and any(_number(value) for value in (evidence.market_price, payload.get("price"), payload.get("current_price"), payload.get("end_close")))
    if metric in PRICE_METRICS:
        return evidence.kind == "price_window" and metric_record(evidence, metric) is not None
    if metric in TECHNICAL_METRICS:
        if evidence.kind != "technical_snapshot":
            return False
        if metric == "support_resistance":
            return metric_record(evidence, "support") is not None and metric_record(evidence, "resistance") is not None
        return metric_record(evidence, metric) is not None
    if metric in FINANCIAL_METRICS | MACRO_METRICS:
        return metric_record(evidence, metric) is not None
    if metric == "dividend_announcement":
        return metric_record(evidence, metric) is not None
    return True


def period_for(evidence, record: dict | None = None) -> tuple[str, str, str]:
    payload = payload_for(evidence)
    data = record or {}
    return (
        str(data.get("period_start") or evidence.period_start or payload.get("period_start") or ""),
        str(data.get("period_end") or evidence.period_end or payload.get("period_end") or ""),
        str(data.get("unit") or data.get("currency") or evidence.unit or evidence.currency or payload.get("currency") or ""),
    )


def time_scope_matches(evidence, scope: dict, record: dict | None = None) -> bool:
    payload = payload_for(evidence)
    kind = scope.get("kind")
    if kind == "trading_sessions":
        if evidence.kind != "price_window" or payload.get("sessions") != scope.get("count"):
            return False
        return scope.get("completed_only") is not True or payload.get("completed_only") is True
    if kind in {"fiscal_quarter", "fiscal_year"}:
        from backend.tools.financial_facts import duration_frequency, fact_date
        data = record or {}
        start, end, _ = period_for(evidence, data)
        if not start or not end:
            records = [row for key in ("metrics", "facts") for row in (payload.get(key) or {}).values() if isinstance(row, dict)]
            records.extend(row for rows in (payload.get("fact_metadata") or {}).values() if isinstance(rows, list) for row in rows[:1] if isinstance(row, dict))
            data = next((row for row in records if row.get("period_start") and row.get("period_end")), data)
            start, end, _ = period_for(evidence, data)
        frequency = str(data.get("frequency") or evidence.frequency or payload.get("frequency") or "").lower()
        expected = {"quarterly", "quarter", "single_quarter"} if kind == "fiscal_quarter" else {"annual", "yearly", "fiscal_year"}
        if frequency not in expected or duration_frequency(start, end) != ("quarterly" if kind == "fiscal_quarter" else "annual"):
            return False
        if any(scope.get(key) and fact_date(scope[key]) != fact_date(value) for key, value in (("period_start", start), ("period_end", end))):
            return False
        as_of = fact_date(scope.get("as_of")) or date.today().isoformat()
        filed = fact_date(data.get("filed") or data.get("published_at") or payload.get("filed") or payload.get("published_at") or evidence.as_of)
        if end > as_of or filed and filed > as_of:
            return False
        if scope.get("completed_only") is True and not filed:
            return False
        selected = payload.get("selected_period")
        if scope.get("selection") == "latest_complete" and selected and end != selected:
            return False
        return True
    return True


def calculation_record(evidence, requirement: dict) -> dict | None:
    spec = requirement.get("calculation")
    if not isinstance(spec, dict):
        return None
    payload = payload_for(evidence)
    for row in payload.get("calculations") or []:
        if (isinstance(row, dict) and row.get("metric") == requirement.get("metric")
                and all(row.get(key) == spec.get(key) for key in ("operation", "baseline"))
                and _number(row.get("value")) and len(row.get("derivation_inputs") or []) == 2
                and time_scope_matches(evidence, requirement.get("time_scope") or {}, row)):
            from backend.tools.financial_calculations import calculate_period_change
            verified = calculate_period_change(*row["derivation_inputs"], **spec)
            if verified and math.isclose(verified["value"], row["value"], rel_tol=1e-9, abs_tol=1e-12):
                return row
    return None


def presentation_reasons(requirement: dict, facts: list) -> list[str]:
    reasons = []
    calculations = [row for fact in facts if (row := calculation_record(fact, requirement)) is not None]
    for field in requirement.get("presentation") or []:
        if field == "itemized":
            continue
        if field == "include_link" and (not facts or any(not (fact.url or payload_for(fact).get("source_url")) for fact in facts)):
            reasons.append("presentation_link_missing")
        if field == "include_date" and (not facts or any(not (payload_for(fact).get("published_at") or payload_for(fact).get("published_date") or fact.as_of or fact.period_end) for fact in facts)):
            reasons.append("presentation_date_missing")
        if field == "include_inputs" and not calculations:
            reasons.append("presentation_inputs_missing")
        if field == "include_formula" and not calculations:
            reasons.append("presentation_" + field.removeprefix("include_") + "_missing")
        provenance = any(all(row.get("source_url") for row in calculation["derivation_inputs"]) for calculation in calculations) if requirement.get("calculation") else bool(facts) and all(fact.url or payload_for(fact).get("source_url") for fact in facts)
        if field == "include_provenance" and not provenance:
            reasons.append("presentation_provenance_missing")
    return reasons


def component_support(component: str, facts: list, scope: dict) -> bool:
    return any(metric_record(fact, component) is not None and time_scope_matches(fact, scope) for fact in facts)


def exact_support_reasons(requirement: dict, facts: list) -> list[str]:
    reasons = []
    status = requirement.get("capability_status")
    if status in {"unsupported", "input_missing"}:
        reasons.append("requirement_unsupported" if status == "unsupported" else "requirement_input_missing")
    if requirement.get("unmapped_qualifiers"):
        reasons.append("requirement_qualifier_unmapped")
    metric = str(requirement.get("metric") or "")
    if metric == "unknown" and requirement.get("kind") != "constraint":
        reasons.append("requirement_metric_unmapped")
    scope = requirement.get("time_scope") if isinstance(requirement.get("time_scope"), dict) else {}
    if scope.get("reporting_basis") in {"consolidated", "parent"}:
        if not any((metric_record(fact, metric) or payload_for(fact)).get("reporting_basis") == scope["reporting_basis"] for fact in facts):
            reasons.append("requirement_reporting_basis_unverified")
    requested_frequency = requirement.get("data_frequency")
    if requested_frequency and requested_frequency not in {"none", "unspecified"}:
        frequencies = {"1d": "daily", "day": "daily", "daily": "daily", "1wk": "weekly", "week": "weekly", "weekly": "weekly", "1mo": "monthly", "month": "monthly", "monthly": "monthly"}
        if not any(frequencies.get(str(fact.frequency or payload_for(fact).get("frequency") or payload_for(fact).get("interval"))) == requested_frequency for fact in facts):
            reasons.append("requirement_sampling_frequency_unverified")
    if scope and facts and not any(time_scope_matches(fact, scope) for fact in facts):
        reasons.append("requirement_period_unverified")
    if requirement.get("calculation") and not any(calculation_record(fact, requirement) for fact in facts):
        reasons.append("requirement_calculation_missing:" + metric)
    if metric in PRICE_METRICS | FINANCIAL_METRICS | MACRO_METRICS | TECHNICAL_METRICS | {"quote", "earnings_estimates"} and not any((metric_record(fact, metric) is not None if metric == "earnings_estimates" else metric_supports(fact, metric)) and time_scope_matches(fact, scope, metric_record(fact, metric)) for fact in facts):
        reasons.append("requirement_metric_missing:" + metric)
    if metric == "dividend_announcement":
        records = [record for fact in facts if (record := metric_record(fact, metric)) is not None]
        if not records:
            reasons.append("requirement_official_declaration_missing")
        elif not any(record.get("currency") for record in records):
            reasons.append("requirement_declaration_currency_unverified")
    if metric in {"macro_data", "nonfarm_payroll_change", "unemployment"}:
        if any((payload_for(fact).get("employment_report") or {}).get("periods_match") is False for fact in facts):
            reasons.append("requirement_employment_period_mismatch")
    components = [str(value) for value in requirement.get("components", [])]
    if components and requirement.get("source_text"):
        reasons.extend("requirement_component_missing:" + component for component in components if not component_support(component, facts, scope))
    # 资本分配余缺只能由同一期间、同币种的实际现金支付组成。
    if metric == "capital_allocation_surplus":
        required = ("operating_cash_flow", "capital_expenditure", "dividends_paid", "repurchases_paid")
        periods = []
        for component in required:
            matches = {period_for(fact, record) for fact in facts if (record := metric_record(fact, component)) is not None}
            periods.append({period for period in matches if all(period)})
        if not periods or not set.intersection(*periods):
            reasons.append("capital_allocation_period_mismatch")
    return list(dict.fromkeys(reasons))


def control_support_reasons(requirement: dict, task, facts: list | None = None) -> list[str] | None:
    """仅对可由合同直接核对的约束免除取数；文本解释仍须绑定论据。"""
    if requirement.get("kind") == "input_dependency":
        specs = requirement.get("input_dependency_specs") or []
        if specs:
            return [] if all(isinstance(item, dict) and item.get("available") is True for item in specs) else ["requirement_input_missing"]
        dependencies = requirement.get("input_dependencies") or []
        return [] if dependencies and all(isinstance(item, dict) and item.get("status") in {"provided", "available", "satisfied"} for item in dependencies) else ["requirement_input_missing"]
    if requirement.get("kind") != "constraint":
        return None
    scope = requirement.get("time_scope") or {}
    constraint_type = requirement.get("constraint_type")
    if constraint_type == "deduplicate":
        urls = [fact.url for fact in facts or [] if fact.url]
        from backend.research.news_event_quality import canonical_news_url
        identities = [canonical_news_url(url) for url in urls]
        return [] if len(identities) == len(set(identities)) else ["requirement_duplicate_content"]
    # 约束自身绑定了财期时，按同期数据结构核对；模型给出的维度名不作为必要条件。
    if constraint_type in {None, "other"} and scope.get("kind") in {"fiscal_quarter", "fiscal_year"}:
        metrics = list(dict.fromkeys(row.get("metric") for row in task.answer_requirements
            if row.get("metric") in FINANCIAL_METRICS and (row.get("time_scope") or {}).get("kind") == scope["kind"]))
        scoped = [fact for fact in facts or [] if time_scope_matches(fact, scope)]
        periods = []
        for metric in metrics:
            matching = {period_for(fact, record)[:2] for fact in scoped if (record := metric_record(fact, metric)) is not None}
            periods.append({period for period in matching if all(period)})
        if periods:
            return [] if set.intersection(*periods) else ["requirement_period_unverified"]
        return [] if any(all(period_for(fact)[:2]) for fact in scoped) else ["requirement_period_unverified"]
    if constraint_type in {None, "other"} and scope.get("kind") in {"latest_quote", "trading_sessions"} and scope.get("selection") == "latest_complete" and scope.get("completed_only") is True:
        for fact in facts or []:
            data = payload_for(fact)
            if scope["kind"] == "latest_quote" and fact.kind == "price_snapshot" and fact.market_price is not None and fact.as_of and data.get("source_time_status") != "unknown" and data.get("market_session") in {"regular_close", "continuous_close"}:
                return []
            dates = data.get("expected_session_dates") or []
            if fact.kind == "price_window" and data.get("completed_only") is True and dates and dates[-1] == data.get("period_end") and not data.get("missing_session_dates"):
                return []
        return ["requirement_completed_session_unverified"]
    if constraint_type == "source_policy":
        from backend.research.news_event_quality import news_source_tier

        policy = requirement.get("source_requirement")
        if not policy:
            policy = next((row.get("source_requirement") for row in requirement.get("constraints", []) if row.get("source_text") == requirement.get("source_text")), None)
        if policy not in {"primary", "attributed", "traceable"}:
            return ["requirement_source_policy_unverified"]
        if not facts:
            return ["requirement_evidence_missing"]
        for fact in facts:
            data = payload_for(fact)
            url = str(fact.url or data.get("source_url") or "")
            host = (urlsplit(url).hostname or "").lower()
            tier = news_source_tier(url, fact.subject or "")
            primary = tier == "primary" or host in {"fred.stlouisfed.org", "www.bls.gov", "www.bea.gov", "www.federalreserve.gov"}
            linked = data.get("primary_source_url")
            if linked and data.get("primary_source_content_read") is True:
                primary = primary or news_source_tier(linked, fact.subject or "") == "primary"
            if policy == "primary" and not primary:
                return ["requirement_primary_source_missing"]
            if policy == "attributed" and not primary and tier != "established_media":
                return ["requirement_attributed_source_missing"]
            if policy == "traceable" and not url.startswith(("https://", "http://")):
                provider = str(fact.source_name or data.get("source") or "").casefold()
                if provider not in {"fred", "sec", "sec_edgar", "sec_companyfacts", "yfinance", "yahoo", "twelve_data", "twelvedata", "finnhub", "alpha_vantage", "akshare"} or not fact.as_of:
                    return ["requirement_traceable_source_missing"]
        return []
    if constraint_type == "exclude_comparison":
        return ["excluded_comparison_executed"] if task.render_kind == "compare" or task.operation == "compare" else []
    if constraint_type == "exclude_dimension":
        aliases = {"fundamental": "fundamental_quality", "news": "news_catalysts", "risk": "risk_level", "technical": "technical_quality", "valuation": "valuation_reasonableness", "price": "performance"}
        source = str(requirement.get("source_text") or "")
        typed = [item for item in requirement.get("constraints", []) if item.get("constraint_type") == constraint_type]
        # 约束原文通常是要求原文的子串，例如“不展开基本面”位于整句限制中。
        constraints = [item for item in typed if item.get("source_text") and str(item["source_text"]) in source]
        excluded = {aliases.get(item.get("dimension"), item.get("dimension")) for item in constraints}
        excluded.discard(None)
        if not excluded:
            return ["requirement_constraint_unverified"]
        return ["excluded_dimension_executed"] if excluded.intersection(task.requested_dimensions) else []
    # 来源限制、事实与情景分离需要实际证据/解释，不能仅凭计划声明通过。
    return None


def attached_source_policy_reasons(requirement: dict, task, facts: list) -> list[str]:
    """附属来源约束同样生效，不依赖模型另列一个重复的约束任务。"""
    scoped_kinds = {
        "news": {"news_context", "event_calendar", "transcript_context", "filing_context"},
        "news_catalysts": {"news_context", "event_calendar", "transcript_context", "filing_context"},
        "macro": {"macro_context"}, "macro_impact": {"macro_context"},
        "fundamental": {"fundamental_snapshot", "filing_context", "capital_allocation", "company_profile"},
        "fundamental_quality": {"fundamental_snapshot", "filing_context", "capital_allocation", "company_profile"},
        "technical": {"technical_snapshot", "price_window"}, "technical_quality": {"technical_snapshot", "price_window"},
        "price": {"price_snapshot", "price_window"}, "performance": {"price_snapshot", "price_window"},
    }
    reasons = []
    for constraint in requirement.get("constraints") or []:
        if constraint.get("constraint_type") != "source_policy":
            continue
        kinds = scoped_kinds.get(constraint.get("dimension"))
        relevant = [fact for fact in facts if not kinds or fact.kind in kinds]
        if kinds and not relevant and set(requirement.get("evidence_kinds") or []).isdisjoint(kinds):
            continue
        check = {**constraint, "kind": "constraint"}
        reasons.extend(control_support_reasons(check, task, relevant) or [])
    return list(dict.fromkeys(reasons))


__all__ = ["attached_source_policy_reasons", "calculation_record", "presentation_reasons", "control_support_reasons", "exact_support_reasons", "metric_supports", "time_scope_matches"]
