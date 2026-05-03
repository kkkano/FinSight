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


def test_validate_plan_ir_accepts_task_ids_on_steps():
    payload = {
        "goal": "分析谷歌新闻和微软涨幅",
        "subject": {"subject_type": "company", "tickers": ["GOOGL"]},
        "output_mode": "brief",
        "tasks": [
            {"id": "task_1", "subject_type": "company", "tickers": ["GOOGL"], "operation": "fetch"},
            {"id": "task_2", "subject_type": "company", "tickers": ["MSFT"], "operation": "price"},
        ],
        "steps": [
            {
                "id": "s1",
                "kind": "tool",
                "name": "get_company_news",
                "inputs": {"ticker": "GOOGL"},
                "task_ids": ["task_1"],
                "task_id": "task_1",
            },
            {
                "id": "s2",
                "kind": "tool",
                "name": "get_stock_price",
                "inputs": {"ticker": "MSFT"},
                "task_ids": ["task_2"],
                "task_id": "task_2",
            },
        ],
        "synthesis": {"style": "structured", "sections": ["GOOGL:fetch", "MSFT:price"]},
        "budget": {"max_rounds": 1, "max_tools": 4},
    }

    plan = validate_plan_ir(payload)
    assert plan.steps[0].task_ids == ["task_1"]
    assert plan.steps[1].task_id == "task_2"


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
