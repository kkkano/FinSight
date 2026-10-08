from dataclasses import asdict

import pytest

from backend.agents.price_agent import PriceAgent
from backend.graph.synthesis.research_synthesis import normalize_evidence
from backend.graph.synthesis.task_outcomes import TaskDescriptor
from backend.graph.execution.evidence_tools import evidence_contract_metadata


def _snapshot(agent, payload):
    return agent._build_price_behavior_snapshot(
        ticker="0700.HK", quote_payload=payload, history_payload={}, benchmark_histories={},
        option_metrics={}, drawdown_summary=None, event_explanation={},
    ).to_dict()


def _normalized_quote(output, *, execution_projected=False, symbol="0700.HK"):
    descriptor = TaskDescriptor(
        task_id="task1", title="腾讯报价", priority=20, order_index=0, operation="price",
        subject_label=symbol, tickers=[symbol], request_frame_id="frame1", render_kind="single",
        render_group_id="frame1", intent_status="ready", required_step_ids=["s1"],
        required_evidence=["price_snapshot"], error_codes=[],
    )
    raw_evidence = []
    if execution_projected:
        for evidence in output.evidence:
            raw = {**asdict(evidence), "published_date": output.as_of, "step_id": "s1"}
            raw.update(evidence_contract_metadata(raw, producer_name="price_agent", producer_kind="agent", required_evidence=["price_snapshot"]))
            if evidence.meta.get("metric_key") == "price_quote" and evidence.meta.get("source_time_status") == "unknown":
                assert raw["published_date"] is None
            raw_evidence.append(raw)
    normalized = normalize_evidence(
        task_descriptors=[descriptor],
        plan_steps=[{"id": "s1", "kind": "agent", "name": "price_agent", "task_ids": ["task1"], "inputs": {"ticker": symbol}}],
        agent_outputs={"s1": asdict(output)}, raw_evidence_by_task={"task1": raw_evidence} if execution_projected else {},
    )
    return next(item for item in normalized.evidence_by_task["task1"] if item.metadata.get("metric_key") == "price_quote")


@pytest.mark.parametrize("payload", [
    "0700.HK Current Price: $427.60 | Change: 1.20 (+0.28%) | Provider: fixture_hk | As of: 2026-10-02T08:00:00Z | Currency: HKD",
    {"price": 427.60, "change": 1.20, "change_percent": 0.28, "provider": "fixture_hk", "timestamp": "2026-10-02T08:00:00Z", "currency": "HKD"},
])
def test_quote_source_currency_observation_time_survive_agent_and_normalization(payload):
    agent = PriceAgent(None, None, None)
    snapshot = _snapshot(agent, payload)
    assert snapshot["quote"]["source"] == "fixture_hk"
    assert snapshot["quote"]["currency"] == snapshot["currency"] == "HKD"
    assert snapshot["quote"]["as_of"] == "2026-10-02T08:00:00Z"
    assert snapshot["as_of"] == "2026-10-02T08:00:00Z"
    output = agent._format_snapshot_output("", snapshot)
    quote = next(item for item in output.evidence if item.meta.get("metric_key") == "price_quote")
    assert quote.timestamp == "2026-10-02T08:00:00Z"
    assert quote.source == "fixture_hk"
    normalized = _normalized_quote(output)
    assert normalized.as_of == "2026-10-02T08:00:00Z"
    assert normalized.currency == "HKD"
    assert normalized.source_name == "fixture_hk"
    assert normalized.market_price == 427.6


@pytest.mark.parametrize("payload", ["0700.HK Current Price: $427.60", {"price": 427.6}])
def test_unknown_quote_time_is_not_inherited_from_analysis_timestamp(payload):
    agent = PriceAgent(None, None, None)
    snapshot = _snapshot(agent, payload)
    assert snapshot["quote"]["as_of"] is None
    assert snapshot["as_of"] == ""
    assert snapshot["quote"]["currency"] is None
    snapshot["analyzed_at"] = "2026-10-03T08:00:00Z"
    output = agent._format_snapshot_output("", snapshot)
    assert output.as_of == "2026-10-03T08:00:00Z"
    quote = next(item for item in output.evidence if item.meta.get("metric_key") == "price_quote")
    assert quote.timestamp is None
    assert quote.meta["as_of"] is None
    assert quote.meta["source_time_status"] == "unknown"
    normalized = _normalized_quote(output)
    assert normalized.as_of is None
    assert normalized.currency is None
    assert "报价时间未核验" in output.summary
    assert _normalized_quote(output, execution_projected=True).as_of is None


def test_legacy_price_output_preserves_observation_time_and_unknown_time():
    agent = PriceAgent(None, None, None)
    known = agent._format_output("", "0700.HK Current Price: $427.60 | Provider: fixture_hk | As of: 2026-10-02T08:00:00Z | Currency: HKD")
    assert known.evidence[0].timestamp == "2026-10-02T08:00:00Z"
    assert known.evidence[0].source == "fixture_hk"
    unknown = agent._format_output("", {"price": 427.6})
    assert unknown.evidence[0].timestamp is None
    assert "USD" not in unknown.summary


def test_quote_basis_survives_gateway_legacy_tool_agent_and_normalization(monkeypatch):
    from backend.services.market_data_gateway import MarketDataGateway, _quote_from_kline_provider
    from backend.tools.price import get_stock_price
    from datetime import datetime, timezone

    def source(_symbol, period, _interval):
        assert period == "1mo"
        return {"currency": "USD", "price_basis": "split_adjusted_close", "dividends_included": False,
                "kline_data": [{"time": "2026-10-06", "open": 98, "high": 102, "low": 97, "close": 100, "volume": 10},
                               {"time": "2026-10-07", "open": 101, "high": 103, "low": 100, "close": 102, "volume": 20}]}

    provider = _quote_from_kline_provider(source, clock=lambda: datetime(2026, 10, 8, 15, tzinfo=timezone.utc))
    gateway = MarketDataGateway(providers={}, primary_provider="", quote_providers={"fixture": provider},
                               quote_primary_provider="fixture", quote_secondary_provider=None,
                               quote_trusted_providers={"fixture"}, quote_cache_ttl_seconds=0)
    monkeypatch.setattr("backend.services.market_data_gateway.get_market_data_gateway", lambda: gateway)
    payload = get_stock_price("ADI")
    agent = PriceAgent(None, None, None)
    snapshot = agent._build_price_behavior_snapshot(ticker="ADI", quote_payload=payload, history_payload={},
        benchmark_histories={}, option_metrics={}, drawdown_summary=None, event_explanation={}).to_dict()
    quote = snapshot["quote"]
    assert quote["price_basis"] == "split_adjusted_close"
    assert quote["dividends_included"] is False
    assert quote["market_session"] == "regular_close" and quote["as_of"] == "2026-10-07"
    output = agent._format_snapshot_output("", snapshot)
    normalized = _normalized_quote(output, symbol="ADI")
    assert normalized.metadata["price_basis"] == "split_adjusted_close"
    assert normalized.metadata["dividends_included"] is False
    from backend.graph.renderers.fact_formatters import format_fact
    assert "拆股调整收盘价，不计现金分红" in format_fact(normalized)


def test_unknown_quote_basis_is_not_assumed_from_daily_close_label():
    from backend.utils.quote import parse_quote_payload
    payload = parse_quote_payload("Current Price: $100 | Session: regular_close | Price basis: unknown")
    assert payload is not None and "price_basis" not in payload
