"""研究能力的唯一语义注册：指标、限定字段、证据输入与验证域。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from pydantic import BaseModel, ConfigDict

from backend.graph.intent_contract import MACRO_INDICATOR_KEYS, evidence_plan_for_kinds

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
    "earnings_estimates": ("earnings_forecast", ["earnings_estimates"], "earnings"),
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
    "operating_income", "earnings_date", "earnings_estimates", "dividend_announcement", "macro_data",
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


FINANCIAL_METRICS = frozenset(metric for metric in _DETERMINISTIC_MEASUREMENTS
    if metric in _METRIC_CONTRACTS and set(_METRIC_CONTRACTS[metric][1]) & {"capital_allocation", "filing_context"}
    and metric != "dividend_announcement")
for metric in FINANCIAL_METRICS:
    _METRIC_ATTRIBUTES.setdefault(metric, set()).update(_COMMON_SOURCE_ATTRIBUTES | {"currency", "reporting_basis"})
_REGISTERED_ATTRIBUTES.add("reporting_basis")
FINANCIAL_DEFINITIONS = {
    "revenue": "目标报表口径下的营业收入，不是现金收款",
    "net_income": "目标报表口径下的净利润，不替换成归母净利润",
    "operating_income": "营业利润",
    "operating_cash_flow": "经营活动产生的现金流量净额",
    "capital_expenditure": "购建固定资产、无形资产和其他长期资产支付的现金，正数现金支出",
    "dividends_paid": "实际支付的股利现金，不是宣告派息或与利息合并的现金项目",
    "repurchases_paid": "实际支付的股份回购现金，不是授权额度",
}
FINANCIAL_INPUTS = {
    "free_cash_flow": ("operating_cash_flow", "capital_expenditure"),
    "capital_allocation_surplus": ("operating_cash_flow", "capital_expenditure", "dividends_paid", "repurchases_paid"),
    "dividend_coverage": ("operating_cash_flow", "capital_expenditure", "dividends_paid"),
}


def financial_metric_inputs(metrics):
    return tuple(dict.fromkeys(part for metric in metrics for part in FINANCIAL_INPUTS.get(metric, (metric,))))


@dataclass(frozen=True)
class CapabilitySpec:
    metric: str
    dimension: str
    evidence_kinds: tuple[str, ...]
    facet: str
    attributes: frozenset[str]
    validation: Literal["structured_fact", "cited_analysis"]
    required_input_groups: tuple[InputGroup, ...]
    enrichment: tuple[str, ...] = ()

    def supports_market(self, market: str) -> bool:
        return all(any(any(item["tools"] or item["agents"] for item in evidence_plan_for_kinds([kind], market=market)) for kind in group.any_of)
                   for group in self.required_input_groups) and (market not in {"CN", "HK"} or self.metric not in FINANCIAL_METRICS
            or all(part in FINANCIAL_DEFINITIONS for part in financial_metric_inputs([self.metric])))

    def producers(self, market: str = "US") -> tuple[str, ...]:
        return tuple(dict.fromkeys(name for item in evidence_plan_for_kinds(list(self.evidence_kinds), market=market)
                                   for name in [*item["tools"], *item["agents"]]))


class InputGroup(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    group_id: str
    any_of: list[str]
    requirement_id: str | None = None


def _capability_inputs(metric: str, kinds: list[str]) -> tuple[tuple[InputGroup, ...], tuple[str, ...]]:
    alternatives = {
        "business_model": ("company_profile", "filing_context", "document_context"),
        "competition": ("document_context", "filing_context"),
        "fundamental_quality": ("fundamental_snapshot", "filing_context"),
        "earnings_performance": ("fundamental_snapshot", "filing_context"),
        "revenue": ("filing_context", "fundamental_snapshot"),
        "net_income": ("filing_context", "fundamental_snapshot"),
        "operating_income": ("filing_context", "fundamental_snapshot"),
        "risk_level": ("risk_profile", "filing_context", "document_context"),
    }
    if metric in alternatives:
        choices = alternatives[metric]
        if metric == "fundamental_quality":
            return (InputGroup(group_id="fundamental:agent", any_of=["fundamental_snapshot"]),
                    InputGroup(group_id="fundamental:filing", any_of=["filing_context"])), tuple(kind for kind in kinds if kind not in choices)
        enrichment = tuple(kind for kind in kinds if kind not in choices)
        return (InputGroup(group_id=f"{metric}:basis", any_of=list(choices)),), enrichment
    if metric == "valuation_reasonableness":
        return (InputGroup(group_id="valuation:profile", any_of=["company_profile"]),
                InputGroup(group_id="valuation:basis", any_of=["company_profile", "fundamental_snapshot", "filing_context", "document_context"])), ("earnings_estimates",)
    if metric in FINANCIAL_METRICS and "capital_allocation" in kinds:
        return (InputGroup(group_id=f"{metric}:facts", any_of=["capital_allocation", "filing_context", "fundamental_snapshot"]),), ()
    return tuple(InputGroup(group_id=f"{metric}:{kind}", any_of=[kind]) for kind in kinds), ()


def _build_capability(metric: str, definition: tuple) -> CapabilitySpec:
    dimension, kinds, facet = definition
    groups, enrichment = _capability_inputs(metric, kinds)
    return CapabilitySpec(metric, dimension, tuple(kinds), facet,
                          frozenset(_METRIC_ATTRIBUTES.get(metric, _COMMON_SOURCE_ATTRIBUTES)),
                          "structured_fact" if metric in _DETERMINISTIC_MEASUREMENTS else "cited_analysis", groups, enrichment)


CAPABILITIES = {metric: _build_capability(metric, definition) for metric, definition in _METRIC_CONTRACTS.items()}


def input_groups(requirement: dict) -> list[dict]:
    if isinstance(requirement.get("required_input_groups"), list):
        return requirement["required_input_groups"]
    return [{"group_id": str(kind), "any_of": [kind]} for kind in requirement.get("evidence_kinds", [])]


def task_input_groups(requirements: list[dict]) -> list[dict]:
    return [
        {**group, "group_id": f"{row.get('requirement_id', index)}:{group['group_id']}", "requirement_id": row.get("requirement_id")}
        for index, row in enumerate(requirements) if row.get("kind") not in {"constraint", "input_dependency"}
        and row.get("capability_status") in {"supported", "retrieval_required"}
        for group in input_groups(row)
    ]


REPORTING_BASIS_LABELS = {"consolidated": "合并", "parent": "母公司", "unspecified": "未指定"}


def reporting_basis_value(value: str | None) -> str | None:
    return next((key for key, label in REPORTING_BASIS_LABELS.items() if value in {key, label}), None)


DIMENSION_KINDS: dict[str, set[str]] = {}
for capability in CAPABILITIES.values():
    DIMENSION_KINDS.setdefault(capability.dimension, set()).update(capability.evidence_kinds)
