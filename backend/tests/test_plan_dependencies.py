# -*- coding: utf-8 -*-
"""WP2 DAG：生产 planner 必须输出可执行的显式依赖。"""
from __future__ import annotations

import pytest

from backend.graph.dag_executor import execute_plan_dag
from backend.graph.nodes.policy_gate import policy_gate
from backend.graph.planning.rule_planner import rule_based_planner
from backend.graph.planning.steps import finalize_step_dependencies


def _multi_frame_state() -> dict:
    frames = [
        {
            "frame_id": "q1",
            "lane": "research",
            "subject": {"type": "company", "tickers": ["AAPL"]},
            "evidence_obligations": ["price_snapshot"],
            "required_results": [],
            "legacy_operation": {"name": "price", "confidence": 0.8, "params": {}},
        },
        {
            "frame_id": "q2",
            "lane": "research",
            "subject": {"type": "company", "tickers": ["MSFT"]},
            "evidence_obligations": ["news_context"],
            "required_results": [],
            "legacy_operation": {"name": "fetch", "confidence": 0.8, "params": {"topic": "news"}},
        },
        {
            "frame_id": "q3",
            "lane": "research",
            "subject": {"type": "macro", "tickers": []},
            "evidence_obligations": ["macro_context"],
            "required_results": [],
            "legacy_operation": {"name": "macro_brief", "confidence": 0.8, "params": {}},
        },
    ]
    return {
        "query": "Check AAPL price, MSFT news, then explain Fed rate impact",
        "operation": {"name": "qa", "confidence": 0.5, "params": {}},
        "output_mode": "chat",
        "subject": {
            "subject_type": "company",
            "tickers": ["AAPL", "MSFT"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "tasks": [],
        "request_frame": frames[0],
        "request_frames": frames,
    }


def test_rule_planner_emits_dependencies_between_serial_groups() -> None:
    state = _multi_frame_state()
    plan = rule_based_planner({**state, **policy_gate(state)})["plan_ir"]
    steps = plan["steps"]

    assert len(steps) >= 3
    assert all("depends_on" in step for step in steps)
    assert steps[0]["depends_on"] == []
    assert any(step["depends_on"] for step in steps[1:])
    q2_roots = {step["id"] for step in steps if step.get("parallel_group") == "q2"}
    q2_agents = [step for step in steps if step.get("parallel_group") == "q2_news_agents"]
    assert q2_roots and q2_agents
    assert set(q2_agents[0]["depends_on"]) == q2_roots
    assert all(step["depends_on"] == [] for step in steps if step.get("parallel_group") == "q3")


def _mixed_task_dependency_steps() -> list[dict]:
    return [
        {
            "id": "a-root",
            "kind": "tool",
            "name": "fixture",
            "inputs": {"step": "a-root"},
            "parallel_group": "roots",
            "task_ids": ["task-a"],
            "optional": False,
        },
        {
            "id": "b-root",
            "kind": "tool",
            "name": "fixture",
            "inputs": {"step": "b-root"},
            "parallel_group": "roots",
            "task_ids": ["task-b"],
            "optional": False,
        },
        {
            "id": "a-followup",
            "kind": "tool",
            "name": "fixture",
            "inputs": {"step": "a-followup"},
            "parallel_group": "followups",
            "task_ids": ["task-a"],
            "optional": False,
        },
        {
            "id": "b-followup",
            "kind": "tool",
            "name": "fixture",
            "inputs": {"step": "b-followup"},
            "parallel_group": "followups",
            "task_ids": ["task-b"],
            "optional": False,
        },
    ]


def test_parallel_group_dependencies_stay_within_each_task() -> None:
    steps = finalize_step_dependencies(_mixed_task_dependency_steps())
    by_id = {step["id"]: step for step in steps}

    assert by_id["a-followup"]["depends_on"] == ["a-root"]
    assert by_id["b-followup"]["depends_on"] == ["b-root"]


def test_explicit_empty_depends_on_keeps_step_as_root() -> None:
    steps = finalize_step_dependencies(
        [
            {
                "id": "task-root",
                "parallel_group": "roots",
                "task_ids": ["task-a"],
            },
            {
                "id": "explicit-root",
                "parallel_group": "followups",
                "task_ids": ["task-a"],
                "depends_on": [],
            },
        ]
    )

    assert steps[1]["depends_on"] == []


def test_scoped_and_unscoped_groups_form_global_barriers_without_cross_task_dependencies() -> None:
    steps = finalize_step_dependencies(
        [
            {"id": "global-setup", "parallel_group": "setup"},
            {
                "id": "a-root",
                "parallel_group": "task-roots",
                "task_ids": ["task-a"],
            },
            {
                "id": "b-root",
                "parallel_group": "task-roots",
                "task_ids": ["task-b"],
            },
            {"id": "global-join", "parallel_group": "join"},
            {
                "id": "a-followup",
                "parallel_group": "task-followups",
                "task_ids": ["task-a"],
            },
            {
                "id": "b-followup",
                "parallel_group": "task-followups",
                "task_ids": ["task-b"],
            },
        ]
    )
    by_id = {step["id"]: step for step in steps}

    assert by_id["global-setup"]["depends_on"] == []
    assert by_id["a-root"]["depends_on"] == ["global-setup"]
    assert by_id["b-root"]["depends_on"] == ["global-setup"]
    assert by_id["global-join"]["depends_on"] == ["a-root", "b-root"]
    assert by_id["a-followup"]["depends_on"] == ["global-join"]
    assert by_id["b-followup"]["depends_on"] == ["global-join"]


@pytest.mark.asyncio
async def test_failed_root_does_not_block_other_task_followup() -> None:
    async def fixture(inputs: dict) -> dict:
        if inputs["step"] == "b-root":
            raise RuntimeError("B root failed")
        return {"ok": inputs["step"]}

    steps = finalize_step_dependencies(_mixed_task_dependency_steps())
    artifacts, _events = await execute_plan_dag(
        {"steps": steps},
        tool_invokers={"fixture": fixture},
        agent_invokers={},
        dry_run=False,
    )

    assert artifacts["step_results"]["a-followup"]["status_reason"] == "done"
    assert artifacts["step_results"]["b-followup"]["status_reason"] == "upstream_failed"
