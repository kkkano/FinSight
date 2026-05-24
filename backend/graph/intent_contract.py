# -*- coding: utf-8 -*-
"""Evidence-first request intent contract.

Legacy ``operation`` is still projected for older policy/planner/render code,
but it is not the semantic source of truth.  Contracts are compiled from the
query or resolved frame, then mapped to closed-set evidence obligations.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Literal, NotRequired, TypedDict

from backend.config.ticker_mapping import CN_TO_TICKER, COMPANY_MAP, dedup_tickers, normalize_ticker
from backend.graph.earnings_intent import (
    query_requests_earnings_performance,
    query_requests_earnings_price_impact,
)
from backend.graph.investment_intent import query_requests_investment_opinion
from backend.graph.request_task_contract import wants_no_news_or_links


EvidenceKind = Literal[
    "price_snapshot",
    "company_profile",
    "earnings_estimates",
    "fundamental_snapshot",
    "technical_snapshot",
    "news_context",
    "risk_profile",
    "macro_context",
    "filing_context",
    "performance_comparison",
    "holdings_ownership",
    "options_derivatives",
    "event_calendar",
    "transcript_context",
    "document_context",
]
ProducerKind = Literal["tool_only", "agent_only", "tool_then_agent", "aggregate"]


@dataclass(frozen=True)
class EvidenceDefinition:
    kind: EvidenceKind
    scope: str
    producer: ProducerKind
    tools: tuple[str, ...] = ()
    agents: tuple[str, ...] = ()
    markets: tuple[str, ...] = ("US", "CN", "HK")


class EvidencePlanItem(TypedDict, total=False):
    kind: str
    scope: str
    producer: str
    tools: list[str]
    agents: list[str]


class RenderIntent(TypedDict, total=False):
    shape: str
    dimensions: list[str]


class IntentContract(TypedDict, total=False):
    version: str
    contract_id: str
    frame_id: str
    primary_operation: str
    subject_type: str
    target_scope: str
    primary_tickers: list[str]
    omitted_tickers: NotRequired[list[str]]
    facets: list[str]
    per_ticker_required: bool
    render_intent: RenderIntent
    required_evidence: list[str]
    evidence_plan: list[EvidencePlanItem]
    budget_profile: str
    source: str
    reason: str


_CONTRACT_VERSION = "intent_contract.v1"
EXTERNAL_IMPACT_LIGHT_PROFILE = "external_entity_impact_light"
_HIGH_ORDER_FACETS = {"valuation", "risk", "trend", "earnings", "investment_opinion", "technical", "external_entity_impact"}
_COMPARISON_RELATION_RE = re.compile(r"\b(?:compare|versus|vs|which|who|better|stronger|relative)\b", re.IGNORECASE)
_EXTERNAL_IMPACT_RELATION_RE = re.compile(
    r"(影响|冲击|拖累|利好|利空|受.{0,24}影响|被.{0,24}影响|"
    r"\b(?:impact|impacts|affect|affects|affected|influence|influences|hurt|hurts|benefit|benefits|weigh(?:s)?\s+on|pressure)\b)",
    re.IGNORECASE,
)
_EXTERNAL_IMPACT_BRIDGE_RE = re.compile(
    r"(.{1,40}?)(?:对|对于|会不会|是否|能否|会|可能|could|would|will|might|may).{0,40}?"
    r"(?:影响|冲击|拖累|利好|利空|impact|affect)",
    re.IGNORECASE,
)
_QUESTION_ONLY_EXTERNAL_RE = re.compile(r"^(?:什么|哪些|哪个|为什么|为何|怎么|如何|why|what|which|how)\s*$", re.IGNORECASE)
_EXTERNAL_ENTITY_STOPWORDS = {
    "WHY",
    "WHAT",
    "WHICH",
    "HOW",
    "THIS",
    "THAT",
    "THE",
    "AND",
    "OR",
    "ITS",
    "STOCK",
    "SHARE",
    "SHARES",
    "PRICE",
    "MARKET",
    "CAP",
    "VALUE",
    "RISK",
    "NEWS",
}
_EXTERNAL_THEME_TOKENS = (
    "AI",
    "CPI",
    "PPI",
    "FED",
    "FOMC",
    "ECB",
    "tariff",
    "tariffs",
    "inflation",
    "rates",
    "interest rate",
    "regulation",
    "regulatory",
    "policy",
    "supply chain",
    "export control",
    "人工智能",
    "利率",
    "美联储",
    "通胀",
    "政策",
    "监管",
    "补贴",
    "关税",
    "供应链",
    "出口管制",
)

_EVIDENCE_REGISTRY: dict[EvidenceKind, EvidenceDefinition] = {
    "price_snapshot": EvidenceDefinition(
        "price_snapshot",
        scope="per_ticker",
        producer="tool_only",
        tools=("get_stock_price",),
        markets=("US", "CN"),
    ),
    "company_profile": EvidenceDefinition(
        "company_profile",
        scope="per_ticker",
        producer="tool_only",
        tools=("get_company_info",),
        markets=("US", "CN"),
    ),
    "earnings_estimates": EvidenceDefinition(
        "earnings_estimates",
        scope="per_ticker",
        producer="tool_only",
        tools=("get_earnings_estimates", "get_eps_revisions"),
        markets=("US",),
    ),
    "fundamental_snapshot": EvidenceDefinition(
        "fundamental_snapshot",
        scope="per_ticker",
        producer="agent_only",
        agents=("fundamental_agent",),
    ),
    "technical_snapshot": EvidenceDefinition(
        "technical_snapshot",
        scope="per_ticker",
        producer="tool_then_agent",
        tools=("get_stock_price", "get_technical_snapshot"),
        agents=("technical_agent",),
        markets=("US", "CN"),
    ),
    "news_context": EvidenceDefinition(
        "news_context",
        scope="per_subject",
        producer="tool_then_agent",
        tools=("get_company_news", "get_authoritative_media_news", "score_news_source_reliability"),
        agents=("news_agent",),
    ),
    "risk_profile": EvidenceDefinition(
        "risk_profile",
        scope="per_ticker",
        producer="tool_then_agent",
        tools=("analyze_historical_drawdowns", "get_factor_exposure", "run_portfolio_stress_test"),
        agents=("risk_agent",),
        markets=("US", "CN"),
    ),
    "macro_context": EvidenceDefinition(
        "macro_context",
        scope="per_topic",
        producer="tool_then_agent",
        tools=("get_official_macro_releases", "get_authoritative_media_news", "search"),
        agents=("macro_agent",),
    ),
    "filing_context": EvidenceDefinition(
        "filing_context",
        scope="per_ticker",
        producer="tool_only",
        tools=("get_sec_filings", "get_sec_material_events", "get_sec_company_facts_quarterly", "get_local_market_filings"),
    ),
    "performance_comparison": EvidenceDefinition(
        "performance_comparison",
        scope="multi_subject",
        producer="tool_only",
        tools=("get_performance_comparison",),
        markets=("US", "CN"),
    ),
    "holdings_ownership": EvidenceDefinition(
        "holdings_ownership",
        scope="per_ticker_or_portfolio",
        producer="tool_only",
        tools=(
            "get_institutional_holdings",
            "get_institution_holdings_by_ticker",
            "get_insider_transactions",
            "get_holdings_overlap",
        ),
        markets=("US",),
    ),
    "options_derivatives": EvidenceDefinition(
        "options_derivatives",
        scope="per_ticker",
        producer="tool_only",
        tools=("get_option_chain_metrics",),
        markets=("US",),
    ),
    "event_calendar": EvidenceDefinition(
        "event_calendar",
        scope="per_ticker_or_topic",
        producer="tool_only",
        tools=("get_event_calendar",),
        markets=("US", "CN"),
    ),
    "transcript_context": EvidenceDefinition(
        "transcript_context",
        scope="per_ticker",
        producer="tool_only",
        tools=("get_earnings_call_transcripts",),
    ),
    "document_context": EvidenceDefinition(
        "document_context",
        scope="per_document",
        producer="tool_only",
        tools=("fetch_url_content", "search"),
    ),
}

_EVIDENCE_ALIASES: dict[str, EvidenceKind] = {
    "price_by_ticker": "price_snapshot",
    "company_info_by_ticker": "company_profile",
    "earnings_estimates_by_ticker": "earnings_estimates",
    "fundamental_snapshot_by_ticker": "fundamental_snapshot",
    "technical_snapshot_by_ticker": "technical_snapshot",
    "news_by_ticker": "news_context",
    "earnings_news_by_ticker": "news_context",
    "risk_profile_by_ticker": "risk_profile",
    "comparison_table": "performance_comparison",
    "quote": "price_snapshot",
    "options_metrics": "options_derivatives",
    "transcript": "transcript_context",
}
_SEC_ONLY_TOOLS = {
    "get_sec_filings",
    "get_sec_material_events",
    "get_sec_company_facts_quarterly",
    "get_institutional_holdings",
    "get_institution_holdings_by_ticker",
    "get_insider_transactions",
    "get_holdings_overlap",
}
_LOCAL_MARKET_TOOLS = {"get_local_market_filings"}


def chat_multi_ticker_research_limit() -> int:
    raw = os.getenv("FINSIGHT_CHAT_MULTI_TICKER_RESEARCH_LIMIT")
    if not isinstance(raw, str) or not raw.strip():
        return 3
    try:
        value = int(raw.strip())
    except Exception:
        return 3
    return max(1, min(10, value))


def intent_contract_mode() -> str:
    raw = str(os.getenv("FINSIGHT_INTENT_CONTRACT_MODE") or "enforce").strip().lower()
    return raw if raw in {"off", "shadow", "enforce"} else "enforce"


def _normalized_tickers(tickers: list[str] | tuple[str, ...] | None) -> list[str]:
    return dedup_tickers([normalize_ticker(str(ticker)) for ticker in (tickers or []) if str(ticker).strip()])


def _dedupe(items: list[str] | tuple[str, ...]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _has_valuation_facet(query: str) -> bool:
    text = str(query or "")
    lowered = text.lower()
    return bool(
        "\u4f30\u503c" in text
        or "valuation" in lowered
        or "multiple" in lowered
        or re.search(r"(?<![a-z0-9])(pe|p/e|peg|ev/ebitda)(?![a-z0-9])", lowered)
    )


def _has_risk_facet(query: str) -> bool:
    text = str(query or "")
    lowered = text.lower()
    return bool("\u98ce\u9669" in text or "risk" in lowered or "drawdown" in lowered or "downside" in lowered)


def _has_trend_facet(query: str) -> bool:
    text = str(query or "")
    lowered = text.lower()
    return bool(
        "\u8d70\u52bf" in text
        or "\u8d8b\u52bf" in text
        or "\u540e\u5e02" in text
        or "trend" in lowered
        or "outlook" in lowered
    )


def _has_price_facet(query: str) -> bool:
    text = str(query or "")
    lowered = text.lower()
    return bool(
        "\u4ef7\u683c" in text
        or "\u80a1\u4ef7" in text
        or "\u6da8\u8dcc" in text
        or "\u6da8\u5e45" in text
        or "\u8dcc\u5e45" in text
        or "\u6da8\u4e86" in text
        or "\u8dcc\u4e86" in text
        or "\u884c\u60c5" in text
        or "price" in lowered
        or "quote" in lowered
        or "trading at" in lowered
    )


def _has_news_facet(query: str) -> bool:
    text = str(query or "")
    lowered = text.lower()
    return bool("\u65b0\u95fb" in text or "\u6d88\u606f" in text or "news" in lowered or "headline" in lowered)


def _has_technical_facet(query: str) -> bool:
    text = str(query or "")
    lowered = text.lower()
    return bool(
        "\u6280\u672f" in text
        or "\u5747\u7ebf" in text
        or "technical" in lowered
        or "rsi" in lowered
        or "macd" in lowered
        or "support" in lowered
        or "resistance" in lowered
    )


def _has_macro_facet(query: str) -> bool:
    text = str(query or "")
    lowered = text.lower()
    return bool(
        "\u5229\u7387" in text
        or "\u7f8e\u8054\u50a8" in text
        or "\u964d\u606f" in text
        or "\u52a0\u606f" in text
        or "\u5b8f\u89c2" in text
        or "fed" in lowered
        or "fomc" in lowered
        or "rates" in lowered
        or "macro" in lowered
    )


def _asks_for_mechanism(query: str) -> bool:
    text = str(query or "")
    lowered = text.lower()
    return bool(
        re.search(r"\b(why|how|explain|mechanism)\b", lowered)
        or "\u4e3a\u4ec0\u4e48" in text
        or "\u4e3a\u4f55" in text
        or "\u600e\u4e48" in text
        or "\u5982\u4f55" in text
        or "\u89e3\u91ca" in text
        or "\u673a\u5236" in text
        or "\u539f\u7406" in text
    )


def _declines_live_retrieval(query: str) -> bool:
    text = str(query or "")
    lowered = text.lower()
    return bool(
        re.search(r"\b(do not|don't|dont|no need to|without)\s+(?:look up|search|research|fetch|check)\b", lowered)
        or re.search(r"\bjust\s+explain\b", lowered)
        or "\u4e0d\u67e5" in text
        or "\u4e0d\u7528\u67e5" in text
        or "\u4e0d\u8981\u67e5" in text
        or "\u4e0d\u8981\u641c" in text
        or "\u76f4\u63a5\u89e3\u91ca" in text
    )


def _asks_for_current_or_retrieval(query: str) -> bool:
    text = str(query or "")
    lowered = text.lower()
    if _declines_live_retrieval(text):
        return False
    return bool(
        re.search(
            r"\b(today|latest|current|recent|this week|this month|now|release|decision|print|data|look up|research|search|fetch|check)\b",
            lowered,
        )
        or "\u4eca\u5929" in text
        or "\u6700\u65b0" in text
        or "\u5f53\u524d" in text
        or "\u8fd1\u671f" in text
        or "\u672c\u5468" in text
        or "\u672c\u6708" in text
        or "\u516c\u5e03" in text
        or "\u6570\u636e" in text
        or "\u51b3\u8bae" in text
        or "\u67e5" in text
        or "\u7814\u7a76" in text
    )


def _live_market_proxy_only(tickers: list[str] | tuple[str, ...] | None) -> bool:
    normalized = _normalized_tickers(tickers)
    if not normalized:
        return True
    return all(ticker.startswith("^") or ticker.endswith("=F") or ticker.endswith("-USD") for ticker in normalized)


def _is_mechanism_explanation_without_live_data(
    query: str,
    tickers: list[str] | tuple[str, ...] | None = None,
) -> bool:
    return bool(_asks_for_mechanism(query) and not _asks_for_current_or_retrieval(query) and _live_market_proxy_only(tickers))


def _is_macro_mechanism_explanation(
    query: str,
    tickers: list[str] | tuple[str, ...] | None = None,
    *,
    domain_intent: str = "",
) -> bool:
    if _normalized_tickers(tickers) and not _live_market_proxy_only(tickers):
        return False
    text = str(query or "")
    lowered = text.lower()
    if not (_has_macro_facet(text) or str(domain_intent or "").strip().lower() in {"macro", "finance_concept"}):
        return False
    if not _asks_for_mechanism(text):
        return False
    named_macro_impact = bool(
        re.search(r"\b(fed|fomc|cpi|ppi|ecb)\b", lowered)
        and re.search(r"\b(impact|effect|affect|reaction|move|pressure)\b", lowered)
    ) or bool(
        (
            "\u7f8e\u8054\u50a8" in text
            or "\u8054\u50a8" in text
            or "\u592e\u884c" in text
            or "\u901a\u80c0" in text
            or "CPI" in text
            or "PPI" in text
            or "FOMC" in text
        )
        and ("\u5f71\u54cd" in text or "\u51b2\u51fb" in text or "\u53cd\u5e94" in text)
    )
    if named_macro_impact:
        return False
    return not _asks_for_current_or_retrieval(text)


def _has_holdings_facet(query: str) -> bool:
    text = str(query or "")
    lowered = text.lower()
    return bool(
        "13f" in lowered
        or "form 4" in lowered
        or "insider transaction" in lowered
        or "institutional holding" in lowered
        or "\u6301\u4ed3" in text
        or "\u5185\u90e8\u4eba\u4ea4\u6613" in text
        or "\u673a\u6784\u6301\u4ed3" in text
    )


def _has_filing_facet(query: str) -> bool:
    lowered = str(query or "").lower()
    return any(token in lowered for token in ("filing", "10-k", "10-q", "sec", "transcript", "earnings call"))


def _company_aliases_for_tickers(tickers: list[str] | tuple[str, ...] | None) -> set[str]:
    normalized = set(_normalized_tickers(tickers))
    aliases: set[str] = set(normalized)
    for ticker in normalized:
        mapped_name = COMPANY_MAP.get(ticker)
        if isinstance(mapped_name, str):
            aliases.add(mapped_name)
        for alias, value in COMPANY_MAP.items():
            if str(value).upper() == ticker:
                aliases.add(str(alias))
        for alias, value in CN_TO_TICKER.items():
            if str(value).upper() == ticker:
                aliases.add(str(alias))
    return {alias for alias in aliases if alias}


def _remove_company_aliases(query: str, tickers: list[str] | tuple[str, ...] | None) -> str:
    text = str(query or "")
    for alias in sorted(_company_aliases_for_tickers(tickers), key=len, reverse=True):
        if not alias:
            continue
        if re.search(r"[\u4e00-\u9fff]", alias):
            text = text.replace(alias, " ")
        else:
            text = re.sub(rf"(?<![A-Za-z0-9]){re.escape(alias)}(?![A-Za-z0-9])", " ", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def _has_external_entity_marker(query: str, tickers: list[str] | tuple[str, ...] | None) -> bool:
    stripped = _remove_company_aliases(query, tickers)
    lowered = stripped.lower()
    for token in _EXTERNAL_THEME_TOKENS:
        needle = str(token or "").strip()
        if not needle:
            continue
        if re.search(r"^[A-Z]{2,6}$", needle):
            if re.search(rf"(?<![A-Za-z0-9]){re.escape(needle)}(?![A-Za-z0-9])", stripped, re.IGNORECASE):
                return True
        elif needle.lower() in lowered or needle in stripped:
            return True

    for token in re.findall(r"(?<![A-Za-z0-9])(?:[A-Z]{2,6}|[A-Z][A-Za-z0-9&.-]{2,})(?![A-Za-z0-9])", stripped):
        upper = token.upper()
        if upper in _EXTERNAL_ENTITY_STOPWORDS:
            continue
        if upper in {alias.upper() for alias in _company_aliases_for_tickers(tickers) if re.fullmatch(r"[A-Za-z0-9.\-=]+", alias)}:
            continue
        return True

    bridge = _EXTERNAL_IMPACT_BRIDGE_RE.search(stripped)
    if bridge:
        candidate = re.sub(r"[\s,，。？?！!、;；:：]+", "", bridge.group(1) or "")
        candidate = re.sub(r"(研究一下|查一下|看看|帮我|请问|分析一下|explain|check|research)", "", candidate, flags=re.IGNORECASE)
        if candidate and not _QUESTION_ONLY_EXTERNAL_RE.fullmatch(candidate):
            return True
    return False


def _has_external_entity_impact_facet(query: str, tickers: list[str] | tuple[str, ...] | None) -> bool:
    company_like_tickers = [
        ticker
        for ticker in _normalized_tickers(tickers)
        if not (ticker.startswith("^") or ticker.endswith("=F") or ticker.endswith("-USD"))
    ]
    if not company_like_tickers:
        return False
    if query_requests_earnings_price_impact(query):
        return False
    if not _EXTERNAL_IMPACT_RELATION_RE.search(str(query or "")):
        return False
    return _has_external_entity_marker(query, company_like_tickers)


def _derive_facets(query: str, *, domain_intent: str = "", tickers: list[str] | tuple[str, ...] | None = None) -> list[str]:
    facets: list[str] = []
    macro_mechanism_explanation = _is_macro_mechanism_explanation(query, tickers, domain_intent=domain_intent)
    live_market_mechanism_explanation = _is_mechanism_explanation_without_live_data(query, tickers)
    if _has_external_entity_impact_facet(query, tickers):
        facets.append("external_entity_impact")
    if _has_valuation_facet(query):
        facets.append("valuation")
    earnings_price_impact = query_requests_earnings_price_impact(query)
    if earnings_price_impact or query_requests_earnings_performance(query):
        facets.append("earnings")
        if earnings_price_impact:
            facets.append("price")
    if _has_risk_facet(query):
        facets.append("risk")
    if _has_trend_facet(query):
        facets.append("trend")
    if _has_technical_facet(query) or domain_intent == "technical":
        facets.append("technical")
    if not wants_no_news_or_links(query) and (_has_news_facet(query) or domain_intent == "news"):
        facets.append("news")
    if (_has_price_facet(query) or domain_intent == "quote") and not live_market_mechanism_explanation:
        facets.append("price")
    if (_has_macro_facet(query) or domain_intent in {"macro", "finance_concept"}) and not macro_mechanism_explanation:
        facets.append("macro")
    if _has_holdings_facet(query) or domain_intent == "holdings":
        facets.append("holdings")
    if _has_filing_facet(query):
        facets.append("filing")
    if query_requests_investment_opinion(query) or domain_intent == "investment_opinion":
        facets.append("investment_opinion")
    return list(dict.fromkeys(facets))


def _required_evidence_for_facets(facets: list[str], *, per_ticker_required: bool) -> list[str]:
    evidence: list[str] = []
    facet_set = set(facets)
    if "external_entity_impact" in facet_set:
        evidence.extend(["price_snapshot", "news_context", "risk_profile"])
    if "valuation" in facet_set:
        evidence.extend(["price_snapshot", "company_profile", "earnings_estimates", "fundamental_snapshot"])
    if "earnings" in facet_set:
        evidence.extend(["company_profile", "earnings_estimates", "fundamental_snapshot", "news_context", "event_calendar", "transcript_context", "filing_context"])
        if "price" in facet_set:
            evidence.append("risk_profile")
    if "risk" in facet_set:
        evidence.extend(["price_snapshot", "risk_profile"])
    if "technical" in facet_set or "trend" in facet_set:
        evidence.extend(["price_snapshot", "technical_snapshot", "options_derivatives"])
    if "news" in facet_set:
        evidence.append("news_context")
    if "price" in facet_set:
        evidence.append("price_snapshot")
    if "macro" in facet_set:
        evidence.append("macro_context")
    if "holdings" in facet_set:
        evidence.append("holdings_ownership")
    if "filing" in facet_set:
        evidence.extend(["filing_context", "transcript_context"])
    if "investment_opinion" in facet_set:
        evidence.extend(["price_snapshot", "technical_snapshot", "news_context", "company_profile", "fundamental_snapshot", "risk_profile"])
    if not per_ticker_required and "price_performance" in facet_set:
        evidence.append("performance_comparison")
    return _dedupe(evidence)


def _comparison_dimensions(facets: list[str]) -> list[str]:
    dims: list[str] = []
    for facet in facets:
        if facet == "valuation":
            dims.append("valuation_reasonableness")
        elif facet == "risk":
            dims.append("risk_level")
        elif facet == "earnings":
            dims.append("earnings_impact")
        elif facet == "trend":
            dims.append("trend_quality")
        elif facet == "investment_opinion":
            dims.append("investment_attractiveness")
        elif facet == "technical":
            dims.append("technical_quality")
        elif facet == "news":
            dims.append("news_catalysts")
        elif facet == "external_entity_impact":
            dims.append("external_impact")
        elif facet == "price_performance":
            dims.append("performance")
    return dims or ["performance"]


def canonical_evidence_kinds(required_evidence: list[str] | tuple[str, ...] | None) -> list[str]:
    kinds: list[str] = []
    for raw in required_evidence or []:
        key = str(raw or "").strip()
        kind = _EVIDENCE_ALIASES.get(key, key)
        if kind in _EVIDENCE_REGISTRY:
            kinds.append(kind)
    return _dedupe(kinds)


def evidence_registry() -> dict[str, EvidenceDefinition]:
    return dict(_EVIDENCE_REGISTRY)


def _tool_available_for_market(tool_name: str, market: str) -> bool:
    market_norm = str(market or "US").strip().upper() or "US"
    if tool_name in _SEC_ONLY_TOOLS:
        return market_norm == "US"
    if tool_name in _LOCAL_MARKET_TOOLS:
        return market_norm in {"CN", "HK"}
    markets: set[str] | None = None
    for definition in _EVIDENCE_REGISTRY.values():
        if tool_name in definition.tools:
            markets = set(definition.markets)
            break
    return True if markets is None else market_norm in markets


def evidence_tools_for_kinds(required_evidence: list[str] | tuple[str, ...] | None, *, market: str = "US") -> list[str]:
    tools: list[str] = []
    market_norm = str(market or "US").strip().upper() or "US"
    for kind in canonical_evidence_kinds(required_evidence):
        definition = _EVIDENCE_REGISTRY[kind]  # type: ignore[index]
        if market_norm not in definition.markets:
            continue
        tools.extend(tool for tool in definition.tools if _tool_available_for_market(tool, market_norm))
    return _dedupe(tools)


def evidence_agents_for_kinds(required_evidence: list[str] | tuple[str, ...] | None, *, market: str = "US") -> list[str]:
    agents: list[str] = []
    market_norm = str(market or "US").strip().upper() or "US"
    for kind in canonical_evidence_kinds(required_evidence):
        definition = _EVIDENCE_REGISTRY[kind]  # type: ignore[index]
        if market_norm in definition.markets:
            agents.extend(definition.agents)
    return _dedupe(agents)


def evidence_plan_for_kinds(required_evidence: list[str] | tuple[str, ...] | None, *, market: str = "US") -> list[EvidencePlanItem]:
    plan: list[EvidencePlanItem] = []
    market_norm = str(market or "US").strip().upper() or "US"
    for kind in canonical_evidence_kinds(required_evidence):
        definition = _EVIDENCE_REGISTRY[kind]  # type: ignore[index]
        if market_norm not in definition.markets:
            continue
        plan.append(
            {
                "kind": definition.kind,
                "scope": definition.scope,
                "producer": definition.producer,
                "tools": [tool for tool in definition.tools if _tool_available_for_market(tool, market_norm)],
                "agents": list(definition.agents),
            }
        )
    return plan


def evidence_plan_for_contract(contract: dict[str, Any] | None, *, market: str = "US") -> list[EvidencePlanItem]:
    required = contract.get("required_evidence") if isinstance(contract, dict) else []
    return evidence_plan_for_kinds(required if isinstance(required, list) else [], market=market)


def derive_intent_contract(
    *,
    query: str,
    tickers: list[str] | tuple[str, ...] | None,
    output_mode: str,
    comparison_requested: bool = False,
    domain_intent: str = "",
    lightweight_requested: bool = False,
    subject_type: str = "company",
    frame_id: str = "frame_1",
) -> IntentContract:
    normalized = _normalized_tickers(list(tickers or []))
    target_scope = "multi" if len(normalized) >= 2 else ("single" if len(normalized) == 1 else "unknown")
    relation_comparison_requested = bool(
        comparison_requested
        or (target_scope == "multi" and _COMPARISON_RELATION_RE.search(str(query or "")))
    )
    facets = _derive_facets(query, domain_intent=domain_intent, tickers=normalized)
    subject = str(subject_type or "company").strip().lower() or "company"
    if subject == "macro":
        facets = [facet for facet in facets if facet in {"macro", "news", "risk"}]
        if "macro" not in facets and not _is_macro_mechanism_explanation(query, normalized, domain_intent=domain_intent or subject):
            facets.append("macro")
    if relation_comparison_requested and not facets:
        facets = ["price_performance"]

    per_ticker_required = bool(
        target_scope == "multi"
        and relation_comparison_requested
        and set(facets).intersection(_HIGH_ORDER_FACETS)
    )
    limit = chat_multi_ticker_research_limit() if str(output_mode or "").strip().lower() == "chat" else 10
    primary_tickers = normalized[:limit] if per_ticker_required else normalized
    omitted_tickers = normalized[limit:] if per_ticker_required else []
    shape = "compare" if relation_comparison_requested and target_scope == "multi" else "answer"

    primary_operation = "research" if per_ticker_required else ("compare" if shape == "compare" else "qa")
    mode = str(output_mode or "").strip().lower()
    if "external_entity_impact" in facets and mode in {"chat", "brief"}:
        budget_profile = EXTERNAL_IMPACT_LIGHT_PROFILE
    elif "valuation" in facets and per_ticker_required and mode in {"chat", "brief"}:
        budget_profile = "valuation_compare_light"
    elif "valuation" in facets and per_ticker_required:
        budget_profile = "valuation_compare"
    elif "investment_opinion" in facets and per_ticker_required:
        budget_profile = "investment_opinion_compare"
    elif per_ticker_required:
        budget_profile = "per_ticker_compare"
    else:
        budget_profile = "light_compare" if shape == "compare" else "default"

    required_evidence = _required_evidence_for_facets(facets, per_ticker_required=per_ticker_required)
    if budget_profile == "valuation_compare_light":
        required_evidence = [kind for kind in required_evidence if kind != "fundamental_snapshot"]
    contract: IntentContract = {
        "version": _CONTRACT_VERSION,
        "contract_id": f"contract_{frame_id}",
        "frame_id": frame_id,
        "primary_operation": primary_operation,
        "subject_type": subject,
        "target_scope": target_scope,
        "primary_tickers": primary_tickers,
        "facets": facets,
        "per_ticker_required": per_ticker_required,
        "render_intent": {"shape": shape, "dimensions": _comparison_dimensions(facets)},
        "required_evidence": required_evidence,
        "evidence_plan": evidence_plan_for_kinds(required_evidence),
        "budget_profile": budget_profile,
        "source": "deterministic_semantic_facets",
        "reason": "contract compiled from query/frame evidence obligations, not from legacy operation",
    }
    if omitted_tickers:
        contract["omitted_tickers"] = omitted_tickers
    return contract


def requires_per_ticker_research(contract: dict[str, Any] | None) -> bool:
    return bool(isinstance(contract, dict) and contract.get("per_ticker_required"))


def is_valuation_contract(contract: dict[str, Any] | None) -> bool:
    facets = contract.get("facets") if isinstance(contract, dict) else None
    return isinstance(facets, list) and "valuation" in {str(f) for f in facets}


def is_research_compare_contract(contract: dict[str, Any] | None) -> bool:
    if not isinstance(contract, dict):
        return False
    render_intent = contract.get("render_intent")
    return bool(isinstance(render_intent, dict) and render_intent.get("shape") == "compare" and contract.get("per_ticker_required"))


def _contract_params(contract: dict[str, Any] | None) -> dict[str, Any]:
    facets = contract.get("facets") if isinstance(contract, dict) else []
    required = contract.get("required_evidence") if isinstance(contract, dict) else []
    params = {
        "facets": [str(f) for f in facets if str(f).strip()] if isinstance(facets, list) else [],
        "required_evidence": canonical_evidence_kinds(required if isinstance(required, list) else []),
        "intent_contract_id": str(contract.get("contract_id") or "") if isinstance(contract, dict) else "",
    }
    budget_profile = str(contract.get("budget_profile") or "").strip() if isinstance(contract, dict) else ""
    if budget_profile:
        params["budget_profile"] = budget_profile
        params["evidence_profile"] = budget_profile
    return params


def evidence_focused_operation(contract: dict[str, Any] | None) -> dict[str, Any]:
    facets = contract.get("facets") if isinstance(contract, dict) else []
    facet_set = {str(f) for f in facets} if isinstance(facets, list) else set()
    params = _contract_params(contract)
    if isinstance(contract, dict) and contract.get("budget_profile"):
        params["budget_profile"] = str(contract.get("budget_profile") or "")
        params["evidence_profile"] = str(contract.get("budget_profile") or "")
    if "technical" in facet_set and not {"valuation", "risk", "investment_opinion"}.intersection(facet_set):
        return {"name": "technical", "confidence": 0.84, "params": params}
    if "external_entity_impact" in facet_set:
        return {"name": "analyze_impact", "confidence": 0.84, "params": params}
    if "earnings" in facet_set and "price" in facet_set:
        return {"name": "earnings_impact", "confidence": 0.84, "params": params}
    if "earnings" in facet_set:
        return {"name": "earnings_performance", "confidence": 0.84, "params": params}
    focus = "investment_opinion"
    if "valuation" in facet_set:
        focus = "valuation"
    elif "risk" in facet_set:
        focus = "risk"
    params["evidence_focus"] = focus
    if focus == "valuation":
        params["facets"] = ["valuation"]
    return {"name": "investment_opinion", "confidence": 0.86 if focus == "valuation" else 0.84, "params": params}


def legacy_operation_for_contract(contract: dict[str, Any] | None, *, subject_type: str = "company") -> dict[str, Any]:
    facets = contract.get("facets") if isinstance(contract, dict) else []
    facet_set = {str(f) for f in facets} if isinstance(facets, list) else set()
    params = _contract_params(contract)
    subject = str(subject_type or "company").strip().lower()
    if isinstance(contract, dict):
        render_intent = contract.get("render_intent")
        if isinstance(render_intent, dict) and render_intent.get("shape") == "compare":
            return {"name": "compare", "confidence": 0.82, "params": params}
    if "external_entity_impact" in facet_set:
        return {"name": "analyze_impact", "confidence": 0.84, "params": params}
    if subject == "macro" or "macro" in facet_set:
        return {"name": "macro_brief", "confidence": 0.78, "params": params}
    if "holdings" in facet_set:
        return {"name": "holdings", "confidence": 0.82, "params": params}
    if "earnings" in facet_set and "price" in facet_set:
        return {"name": "earnings_impact", "confidence": 0.84, "params": params}
    if "earnings" in facet_set:
        return {"name": "earnings_performance", "confidence": 0.84, "params": params}
    if "technical" in facet_set and not {"valuation", "risk"}.intersection(facet_set):
        return {"name": "technical", "confidence": 0.82, "params": params}
    if (
        "trend" in facet_set
        and not {"valuation", "risk", "investment_opinion"}.intersection(facet_set)
    ):
        return {"name": "technical", "confidence": 0.82, "params": params}
    if {"valuation", "risk", "investment_opinion"}.intersection(facet_set):
        return evidence_focused_operation(contract)
    if "news" in facet_set:
        return {"name": "fetch", "confidence": 0.78, "params": {**params, "topic": "news"}}
    if "price" in facet_set:
        return {"name": "price", "confidence": 0.82, "params": params}
    if "filing" in facet_set:
        return {"name": "qa", "confidence": 0.74, "params": params}
    return {"name": "qa", "confidence": 0.68, "params": params}


def synthesis_compare_operation(contract: dict[str, Any] | None) -> dict[str, Any]:
    render_intent = contract.get("render_intent") if isinstance(contract, dict) else {}
    dimensions = render_intent.get("dimensions") if isinstance(render_intent, dict) else []
    facets = contract.get("facets") if isinstance(contract, dict) else []
    budget_profile = str(contract.get("budget_profile") or "") if isinstance(contract, dict) else ""
    primary_tickers = contract.get("primary_tickers") if isinstance(contract, dict) and isinstance(contract.get("primary_tickers"), list) else []
    omitted_tickers = contract.get("omitted_tickers") if isinstance(contract, dict) and isinstance(contract.get("omitted_tickers"), list) else []
    params: dict[str, Any] = {
        "synthesis_only": True,
        "data_profile": "research_synthesis",
        "comparison_dimensions": list(dimensions or []),
        "facets": [str(f) for f in facets if str(f).strip()] if isinstance(facets, list) else [],
        "required_evidence": canonical_evidence_kinds(
            contract.get("required_evidence") if isinstance(contract, dict) and isinstance(contract.get("required_evidence"), list) else []
        ),
        "intent_contract_id": str(contract.get("contract_id") or "") if isinstance(contract, dict) else "",
    }
    if budget_profile:
        params["budget_profile"] = budget_profile
        params["comparison_data_profile"] = budget_profile
    if omitted_tickers:
        params["research_ticker_limit"] = len(primary_tickers)
        params["omitted_tickers"] = [str(ticker) for ticker in omitted_tickers]
    return {
        "name": "compare",
        "confidence": 0.86,
        "params": params,
    }


__all__ = [
    "EvidenceDefinition",
    "EvidenceKind",
    "EvidencePlanItem",
    "EXTERNAL_IMPACT_LIGHT_PROFILE",
    "IntentContract",
    "canonical_evidence_kinds",
    "derive_intent_contract",
    "evidence_agents_for_kinds",
    "evidence_focused_operation",
    "evidence_plan_for_contract",
    "evidence_plan_for_kinds",
    "evidence_registry",
    "evidence_tools_for_kinds",
    "intent_contract_mode",
    "is_research_compare_contract",
    "is_valuation_contract",
    "legacy_operation_for_contract",
    "requires_per_ticker_research",
    "synthesis_compare_operation",
]
