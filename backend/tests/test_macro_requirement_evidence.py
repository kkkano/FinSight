"""就业人数、比率、观察月份与发布时间跨工具和展示层保真。"""
from copy import deepcopy

from backend.graph.execution.evidence_tools import append_tool_evidence
from backend.graph.renderers.fact_formatters import format_fact
from backend.graph.synthesis.research_synthesis import normalize_evidence
from backend.graph.synthesis.requirement_support import exact_support_reasons
from backend.graph.synthesis.task_outcomes import build_task_descriptors


def _normalize(payload):
    task = {"id": "task", "title": "美国就业", "subject_type": "macro", "subject_label": "美国就业", "tickers": [],
            "operation": {"name": "macro_brief"}, "priority": 0, "order_index": 0, "request_frame_id": "frame",
            "render_kind": "single", "render_group_id": "frame", "required_evidence": ["macro_context"]}
    step = {"id": "fred", "kind": "tool", "name": "get_fred_data", "task_ids": ["task"], "evidence_kinds": ["macro_context"], "inputs": {}}
    descriptors = build_task_descriptors(understanding_tasks=[task], blocked_tasks=[], plan_tasks=[task], plan_steps=[step]).descriptors
    pool = []
    append_tool_evidence(pool, "get_fred_data", "fred", payload, required_evidence=["macro_context"])
    for row in pool:
        row.update(step_id="fred", task_ids=["task"])
    return normalize_evidence(task_descriptors=descriptors, plan_steps=[step], agent_outputs={"fred": {"output": payload}}, raw_evidence_by_task={"task": pool})


def _payload():
    metadata = {}
    for metric, value, unit, series in (("nonfarm_payroll_change", 210000, "persons", "PAYEMS"), ("unemployment", 4.1, "percent", "UNRATE")):
        metadata[metric] = {"metric": metric, "value": value, "unit": unit, "series_id": series,
            "frequency": "monthly", "report_month": "2026-09", "observation_date": "2026-09-01",
            "period_start": "2026-09-01", "period_end": "2026-09-30", "source_updated_at": "2026-10-02T14:00:00+00:00",
            "published_at": None, "source_url": f"https://fred.stlouisfed.org/series/{series}"}
    return {"status": "success", "nonfarm_payroll_change": 210000, "unemployment": 4.1,
        "as_of": "2026-10-04T12:00:00+00:00", "indicator_metadata": metadata,
        "employment_report": {"report_month": "2026-09", "periods_match": True, "published_at": None}}


def test_fred_indicators_keep_their_units_and_never_turn_month_or_fetch_time_into_publication():
    normalized = _normalize(_payload())
    assert not normalized.rejected_evidence
    assert len(normalized.evidence_index) == 2
    indexed = {item.metric: item for item in normalized.evidence_index.values()}
    payroll = indexed["nonfarm_payroll_change"]
    assert payroll.unit == "persons" and payroll.period_end == "2026-09-30"
    assert payroll.as_of == "2026-10-02T14:00:00+00:00"
    text = format_fact(payroll, profile="chat")
    assert "210,000人" in text and "210,000%" not in text
    assert "2026-09" in text and "原始发布时间尚未核实" in text
    assert "2026-10-04" not in text
    assert "4.1%" in format_fact(indexed["unemployment"], profile="chat")


def test_employment_mismatched_months_remain_individual_facts_but_not_a_complete_report():
    payload = _payload()
    payload["employment_report"]["periods_match"] = False
    payload["indicator_metadata"]["unemployment"]["report_month"] = "2026-08"
    normalized = _normalize(payload)
    facts = list(normalized.evidence_index.values())
    assert len(facts) == 2
    requirement = {"metric": "macro_data", "source_text": "核对新增就业和失业率", "components": ["nonfarm_payroll_change", "unemployment"]}
    assert "requirement_employment_period_mismatch" in exact_support_reasons(requirement, facts)


def test_missing_payroll_value_does_not_remove_available_unemployment_evidence():
    payload = deepcopy(_payload())
    payload["nonfarm_payroll_change"] = None
    normalized = _normalize(payload)
    assert [item.metric for item in normalized.evidence_index.values()] == ["unemployment"]
