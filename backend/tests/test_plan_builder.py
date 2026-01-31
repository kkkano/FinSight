# -*- coding: utf-8 -*-
"""
PlanBuilder fast-path tests.
"""

from backend.orchestration.plan import PlanBuilder


def test_plan_builder_fast_path_skips_forum():
    plan = PlanBuilder.build_report_plan("price check", "AAPL", ["price"])
    assert plan.steps
    assert all(step.step_type != "forum" for step in plan.steps)


def test_plan_builder_adds_forum_for_multi_agents():
    plan = PlanBuilder.build_report_plan(
        "analyze Tesla", "TSLA", ["price", "news", "technical"]
    )
    assert any(step.step_type == "forum" for step in plan.steps)
