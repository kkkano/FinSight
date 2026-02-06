# -*- coding: utf-8 -*-
from backend.graph.nodes.planner_stub import planner_stub
from backend.graph.plan_ir import plan_ir_json_schema, validate_plan_ir


def test_plan_ir_json_schema_smoke():
    schema = plan_ir_json_schema()
    assert isinstance(schema, dict)
    props = schema.get("properties") or {}
    for key in ("goal", "subject", "output_mode", "steps", "budget"):
        assert key in props


def test_validate_plan_ir_accepts_minimal_payload():
    payload = {
        "goal": "分析影响",
        "subject": {
            "subject_type": "news_item",
            "tickers": [],
            "selection_ids": ["n1"],
            "selection_types": ["news"],
            "selection_payload": [{"type": "news", "id": "n1", "title": "t"}],
        },
        "output_mode": "brief",
        "steps": [],
        "synthesis": {"style": "concise", "sections": []},
        "budget": {"max_rounds": 1, "max_tools": 0},
    }
    plan = validate_plan_ir(payload)
    assert plan.output_mode == "brief"
    assert plan.subject.subject_type == "news_item"


def test_planner_stub_falls_back_on_invalid_output_mode():
    result = planner_stub(
        {
            "query": "分析影响",
            "output_mode": "INVALID",
            "subject": {
                "subject_type": "company",
                "tickers": ["AAPL"],
                "selection_ids": [],
                "selection_types": [],
                "selection_payload": [],
            },
        }
    )
    plan_ir = result.get("plan_ir") or {}
    assert plan_ir.get("output_mode") == "brief"
    assert (result.get("trace") or {}).get("planner", {}).get("fallback") is True

