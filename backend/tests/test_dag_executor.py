# -*- coding: utf-8 -*-
"""WP2-Task5: DAG 执行器——就绪即跑调度、失败闭包跳过、legacy parallel_group 隐式依赖。"""
import asyncio

import pytest

from backend.graph.dag_executor import execute_plan_dag


def make_step(id, name, depends_on=(), kind="tool", optional=False):
    return {"id": id, "kind": kind, "name": name, "inputs": {"step": id},
            "depends_on": list(depends_on), "optional": optional}


@pytest.mark.asyncio
async def test_ready_steps_run_concurrently_and_dependents_wait():
    order: list[str] = []

    async def slow(inputs):
        order.append(f"start:{inputs['step']}")
        await asyncio.sleep(0.05 if inputs["step"] == "a" else 0.01)
        order.append(f"end:{inputs['step']}")
        return {"ok": inputs["step"]}

    plan = {"steps": [make_step("a", "t"), make_step("b", "t"), make_step("c", "t", depends_on=["a", "b"])]}
    artifacts, _ = await execute_plan_dag(plan, tool_invokers={"t": slow}, agent_invokers={}, dry_run=False)
    assert order.index("start:b") < order.index("end:a")          # a、b 并发
    assert order.index("start:c") > order.index("end:a")          # c 等 a
    assert order.index("start:c") > order.index("end:b")          # c 等 b
    assert set(artifacts["step_results"]) == {"a", "b", "c"}


@pytest.mark.asyncio
async def test_required_failure_skips_downstream_but_not_siblings():
    async def tool(inputs):
        if inputs["step"] == "a":
            raise RuntimeError("boom")
        return {"ok": True}

    plan = {"steps": [make_step("a", "t"), make_step("b", "t"),
                      make_step("c", "t", depends_on=["a"]), make_step("d", "t", depends_on=["b"])]}
    artifacts, _ = await execute_plan_dag(plan, tool_invokers={"t": tool}, agent_invokers={}, dry_run=False)
    assert artifacts["step_results"]["c"]["status_reason"] == "upstream_failed"
    assert artifacts["step_results"]["d"]["status_reason"] == "done"
    assert any(e["step_id"] == "a" for e in artifacts["errors"])


@pytest.mark.asyncio
async def test_legacy_parallel_group_plans_get_implicit_dependencies():
    order: list[str] = []

    async def tool(inputs):
        order.append(inputs["step"])
        return {}

    steps = [dict(make_step("a", "t"), parallel_group="g1"),
             dict(make_step("b", "t"), parallel_group="g1"),
             dict(make_step("c", "t"), parallel_group="g2")]
    for s in steps:
        s["depends_on"] = []
    await execute_plan_dag({"steps": steps}, tool_invokers={"t": tool}, agent_invokers={}, dry_run=False)
    assert order.index("c") > order.index("a") and order.index("c") > order.index("b")
