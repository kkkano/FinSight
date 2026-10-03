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


def _normalized_quote(output, *, execution_projected=False):
    descriptor = TaskDescriptor(
        task_id="task1", title="腾讯报价", priority=20, order_index=0, operation="price",
        subject_label="0700.HK", tickers=["0700.HK"], request_frame_id="frame1", render_kind="single",
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
        plan_steps=[{"id": "s1", "kind": "agent", "name": "price_agent", "task_ids": ["task1"], "inputs": {"ticker": "0700.HK"}}],
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
