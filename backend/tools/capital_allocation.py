"""SEC 现金资本分配及财年末普通股合同；缺失值不按零处理。"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from typing import Any

from . import sec
from .financial_facts import FinancialFact, fact_date


_CASH_METRICS = {
    "operating_cash_flow": sec._COMPANYFACTS_METRIC_MAP["operating_cash_flow"][0],
    "capital_expenditure": sec._COMPANYFACTS_METRIC_MAP["capital_expenditures"][0],
    "dividends_paid": ("PaymentsOfDividendsCommonStock", "PaymentsOfDividends"),
    "repurchases_paid": ("PaymentsForRepurchaseOfCommonStock", "PaymentsForRepurchaseOfEquity"),
}
_BALANCE_METRICS = {
    "shares_outstanding": (("CommonStockSharesOutstanding",), ("shares",)),
    "cash_and_equivalents": (("CashAndCashEquivalentsAtCarryingValue",), ("USD",)),
    "debt_current": (("LongTermDebtCurrent",), ("USD",)),
    "debt_noncurrent": (("LongTermDebtNoncurrent",), ("USD",)),
}


def _freeze_payload(payload: dict[str, Any], as_of: str | None) -> dict[str, Any]:
    date_cutoff = date.fromisoformat(as_of) if as_of and len(as_of) == 10 else None
    now = datetime.fromisoformat(as_of.replace("Z", "+00:00")) if as_of else datetime.now(timezone.utc)
    if now.tzinfo is None and date_cutoff is None:
        raise ValueError("as_of_requires_timezone")
    # SEC CompanyFacts 仅给 filed 日期，回放当天无法确定何时公开，故只用之前日期。
    cutoff = (date_cutoff + timedelta(days=1)).isoformat() if date_cutoff else now.astimezone(timezone.utc).date().isoformat()
    latest_end = date_cutoff.isoformat() if date_cutoff else cutoff
    frozen = deepcopy(payload)
    for taxonomy in (frozen.get("facts") or {}).values():
        for obj in taxonomy.values():
            for unit, rows in (obj.get("units") or {}).items():
                obj["units"][unit] = [row for row in rows if isinstance(row, dict)
                    and fact_date(row.get("filed")) and fact_date(row["filed"]) < cutoff
                    and fact_date(row.get("end")) and fact_date(row["end"]) <= latest_end]
    return frozen


def _same_interval(facts: list[FinancialFact]) -> bool:
    return len({(fact.subject, fact.unit, fact.frequency, fact.period_start, fact.period_end) for fact in facts}) == 1


def _debt_burden(facts: dict[str, Any], end: str) -> dict[str, Any] | None:
    components = {key: facts.get(key) for key in ("debt_current", "debt_noncurrent", "cash_and_equivalents")}
    if not any(components[key] for key in ("debt_current", "debt_noncurrent")):
        return None
    missing = [key for key, fact in components.items() if fact is None]
    compatible = not missing and all(fact["accession"] and fact["filed"] for fact in components.values()) and len({(fact["subject"], fact["unit"], fact["period_end"], fact["accession"], fact["filed"])
        for fact in components.values()}) == 1
    component_sum = sum(components[key]["value"] for key in ("debt_current", "debt_noncurrent")) if compatible else None
    cash = components["cash_and_equivalents"]
    return {"subject": next(fact["subject"] for fact in components.values() if fact),
        "metric": "debt_burden", "period_end": end, "frequency": "instant", "unit": "USD",
        "source": "sec_companyfacts", "source_url": next(fact["source_url"] for fact in components.values() if fact),
        "definition": "long_term_debt_current_maturities_and_noncurrent_balance_with_cash",
        "components": components, "long_term_debt_component_sum": component_sum,
        "long_term_debt_minus_cash": component_sum - cash["value"] if compatible else None,
        "complete_for_definition": compatible,
        "missing_components": missing + (["compatible_filing_version"] if not missing and not compatible else []),
        "industrial_financial_subsidiary_split": None,
        "limitations": ["仅长期债务及当期到期部分，未以总负债替代债务；未核对短期借款、租赁或担保。",
            "合并余额不支持工业经营与金融子公司拆分，不能据此单独判断工业经营偿债风险。"],
        "formula": "long_term_debt_current_maturities + long_term_debt_noncurrent - cash_and_equivalents"}


def get_sec_capital_allocation(
    ticker: str, frequency: str = "quarterly", as_of: str | None = None, limit: int = 2,
) -> dict[str, Any]:
    """获取已披露同季度/财年现金支付及可比期末普通股，保留差分申报来源。"""
    symbol = str(ticker or "").strip().upper()
    result: dict[str, Any] = {
        "ticker": symbol, "subject": symbol, "kind": "capital_allocation", "metric": "capital_allocation",
        "source": "sec_companyfacts", "currency": "USD", "unit": "USD", "frequency": frequency,
        "periods": [], "facts": {}, "missing_metrics": [], "error": None,
        "warnings": ["现金支付不代表回购授权；净股数变化不等于回购股数。SEC filed 仅有日期；精确时刻请求仅使用之前提交日期，日期请求按该 UTC 日结束筛选。"],
    }
    try:
        if frequency not in {"quarterly", "annual"} or not 1 <= limit <= 8:
            raise ValueError("invalid_capital_allocation_request")
        if sec._detect_market(symbol) != "US":
            raise ValueError("unsupported_market")
        user_agent = sec._resolve_user_agent()
        if not sec._is_valid_user_agent(user_agent):
            raise ValueError("missing_sec_user_agent")
        headers = sec._sec_headers(user_agent)
        company = sec._load_ticker_map(headers).get(symbol)
        if not company:
            raise ValueError("ticker_not_found")
        cik = company["cik"]
        payload = sec._fetch_companyfacts(cik, headers)
        if payload.get("cik") is None or str(payload["cik"]).lstrip("0") != str(cik).lstrip("0"):
            raise ValueError("issuer_mismatch")
        payload = _freeze_payload(payload, as_of)
        url = sec._SEC_COMPANYFACTS_URL.format(cik=cik)
        result.update(company_name=company.get("title"), cik=cik, source_url=url)
        cash = {metric: sec._extract_companyfacts_facts(payload, concepts=concepts, unit_candidates=("USD",),
            subject=symbol, metric=metric, source_url=url, frequency=frequency)
            for metric, concepts in _CASH_METRICS.items()}
        anchors = sec._extract_companyfacts_facts(payload, concepts=sec._COMPANYFACTS_METRIC_MAP["revenue"][0],
            unit_candidates=("USD",), subject=symbol, metric="revenue", source_url=url, frequency=frequency)
        ends = sorted(set(anchors).union(*(set(series) for series in cash.values())), reverse=True)[:limit]
        balances = {metric: sec._extract_companyfacts_facts(payload, concepts=concepts, unit_candidates=units,
            subject=symbol, metric=metric, source_url=url, instant=True)
            for metric, (concepts, units) in _BALANCE_METRICS.items()}
        for end in ends:
            anchor = anchors.get(end) or next(series[end] for series in cash.values() if end in series)
            facts = {}
            missing = []
            for metric, series in cash.items():
                fact = series.get(end)
                if fact is not None and _same_interval([anchor, fact]):
                    facts[metric] = fact.metadata()
                    if metric in {"dividends_paid", "repurchases_paid"}:
                        facts[metric]["payment_scope"] = "common_equity" if "CommonStock" in (fact.concept or "") else "all_equity"
                else:
                    facts[metric] = None
                    missing.append(metric)
            period = {"period_start": anchor.period_start, "period_end": end, "frequency": frequency,
                "unit": "USD", "facts": facts, "missing_metrics": missing,
                "free_cash_flow": None, "capital_allocation_surplus": None, "cash_coverage_ratio": None,
                "share_count_change": None, "net_share_change": None,
                "dividend_coverage": None, "debt_burden": None}
            period.update({metric: fact["value"] if fact else None for metric, fact in facts.items()})
            if facts["operating_cash_flow"] and facts["capital_expenditure"]:
                period["free_cash_flow"] = facts["operating_cash_flow"]["value"] - facts["capital_expenditure"]["value"]
                if facts["dividends_paid"] and facts["dividends_paid"]["value"] > 0:
                    period["dividend_coverage"] = period["free_cash_flow"] / facts["dividends_paid"]["value"]
                    period["dividend_coverage_formula"] = "(operating_cash_flow - capital_expenditure) / dividends_paid"
            if not missing:
                outflows = sum(facts[name]["value"] for name in ("capital_expenditure", "dividends_paid", "repurchases_paid"))
                period["capital_allocation_surplus"] = facts["operating_cash_flow"]["value"] - outflows
                period["cash_coverage_ratio"] = facts["operating_cash_flow"]["value"] / outflows if outflows else None
                period["formula"] = "operating_cash_flow - capital_expenditure - dividends_paid - repurchases_paid"
            for metric, series in balances.items():
                fact = series.get(end)
                if fact:
                    facts[metric] = fact.metadata()
                    period[metric] = fact.value
            period["debt_burden"] = _debt_burden(facts, end)
            if period["debt_burden"]:
                facts["debt_burden"] = period["debt_burden"]
            if frequency == "annual" and anchor.period_start:
                prior_end = (date.fromisoformat(anchor.period_start) - timedelta(days=1)).isoformat()
                shares = balances["shares_outstanding"]
                start_fact, end_fact = shares.get(prior_end), shares.get(end)
                if start_fact and end_fact and start_fact.concept == end_fact.concept and start_fact.unit == end_fact.unit:
                    period["share_count_change"] = {"start": start_fact.metadata(), "end": end_fact.metadata(),
                        "net_change": end_fact.value - start_fact.value, "net_reduction": start_fact.value - end_fact.value,
                        "unit": "shares", "definition": "fiscal_year_end_common_shares_outstanding",
                        "formula": "ending_common_shares - beginning_common_shares"}
                    period["net_share_change"] = end_fact.value - start_fact.value
                    period["net_share_change_record"] = {"subject": symbol, "metric": "net_share_change",
                        "value": end_fact.value - start_fact.value, "unit": "shares", "frequency": "annual",
                        "period_start": prior_end, "period_end": end, "source": "sec_companyfacts",
                        "source_url": url, "derivation_inputs": [start_fact.metadata(), end_fact.metadata()]}
                    facts["net_share_change"] = period["net_share_change_record"]
                else:
                    missing.append("net_share_change")
            if "shares_outstanding" not in facts:
                period["shares_outstanding"] = None
                missing.append("shares_outstanding")
            if not period["debt_burden"] or not period["debt_burden"]["complete_for_definition"]:
                missing.append("debt_burden")
            if period["dividend_coverage"] is None:
                missing.append("dividend_coverage")
            result["periods"].append(period)
        if result["periods"]:
            result.update({key: value for key, value in result["periods"][0].items() if key != "unit"})
        else:
            result["missing_metrics"] = list(_CASH_METRICS) + (["net_share_change"] if frequency == "annual" else [])
            result["error"] = "no_disclosed_period"
    except Exception as exc:
        result["error"] = str(exc) if isinstance(exc, ValueError) else "capital_allocation_unavailable"
        result["missing_metrics"] = list(_CASH_METRICS) + (["net_share_change"] if frequency == "annual" else [])
    result["structured_data"] = dict(result)
    return result
