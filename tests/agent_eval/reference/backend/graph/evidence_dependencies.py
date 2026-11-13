"""生产者输出与 Agent 消费的证据类型；用于计划、覆盖和执行共享。"""
from __future__ import annotations

from typing import Any

from backend.config.ticker_mapping import normalize_ticker
from backend.graph.intent_contract import evidence_registry


AGENT_INPUT_EVIDENCE: dict[str, set[str]] = {
    "fundamental_agent": {"company_profile", "filing_context", "earnings_estimates"},
    "technical_agent": {"price_snapshot", "technical_snapshot", "options_derivatives"},
    "risk_agent": {"price_snapshot", "risk_profile", "options_derivatives"},
    "news_agent": {"news_context", "event_calendar"},
    "price_agent": {"price_snapshot", "performance_comparison", "technical_snapshot"},
    "macro_agent": {"macro_context", "event_calendar"},
    "deep_search_agent": {"filing_context", "news_context", "document_context", "company_profile"},
}


def producer_evidence_kinds(kind: str, name: str) -> set[str]:
    # 报价是指标计算的输入，本身不证明已经取得技术指标。
    if kind == "tool" and name == "get_stock_price":
        return {"price_snapshot"}
    return {key for key, definition in evidence_registry().items()
            if name in (definition.agents if kind == "agent" else definition.tools)}


def step_evidence_kinds(step: dict[str, Any]) -> set[str]:
    kinds = producer_evidence_kinds(str(step.get("kind")), str(step.get("name")))
    declared = set(step.get("evidence_kinds") or [])
    return kinds.intersection(declared) if declared else kinds


def input_tickers(inputs: dict[str, Any]) -> set[str]:
    values: list[Any] = [inputs.get("ticker")] if inputs.get("ticker") else []
    tickers = inputs.get("tickers")
    if isinstance(tickers, (dict, list, tuple)):
        values.extend(tickers)
    for position in inputs.get("positions", []) if isinstance(inputs.get("positions"), list) else []:
        if isinstance(position, dict):
            values.append(position.get("ticker"))
    return {normalize_ticker(str(value)) for value in values if value}


def step_subjects(step: dict[str, Any]) -> set[str]:
    return input_tickers(step.get("inputs") or {}) or {
        normalize_ticker(str(value)) for value in step.get("subject_tickers", []) if value
    }


def step_task_ids(step: dict[str, Any]) -> set[str]:
    return {str(value) for value in [step.get("task_id"), *(step.get("task_ids") or [])] if value}
