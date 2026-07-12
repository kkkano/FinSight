# -*- coding: utf-8 -*-
from __future__ import annotations

from backend.graph.planning.roles import assign_agent_roles
from backend.graph.renderers.synthesis_vars import _agent_summary
from backend.graph.report_builder import build_report_payload


def test_assign_agent_roles_prefers_operation_lead_and_falls_back_to_first_selected():
    steps = [
        {"id": "n1", "kind": "agent", "name": "news_agent", "inputs": {}},
        {"id": "f1", "kind": "agent", "name": "fundamental_agent", "inputs": {}},
    ]
    assign_agent_roles(steps, operation="investment_opinion")
    assert steps[0]["inputs"]["role"] == "support"
    assert steps[1]["inputs"]["role"] == "lead"

    fallback_steps = [
        {"id": "n1", "kind": "agent", "name": "news_agent", "inputs": {}},
        {"id": "r1", "kind": "agent", "name": "risk_agent", "inputs": {}},
    ]
    assign_agent_roles(fallback_steps, operation="technical")
    assert fallback_steps[0]["inputs"]["role"] == "lead"
    assert fallback_steps[1]["inputs"]["role"] == "support"


def test_assign_agent_roles_uses_each_task_operation():
    steps = [
        {
            "id": "t1-news",
            "kind": "agent",
            "name": "news_agent",
            "task_ids": ["task-1"],
            "inputs": {},
        },
        {
            "id": "t1-fund",
            "kind": "agent",
            "name": "fundamental_agent",
            "task_ids": ["task-1"],
            "inputs": {},
        },
        {
            "id": "t2-risk",
            "kind": "agent",
            "name": "risk_agent",
            "task_ids": ["task-2"],
            "inputs": {},
        },
    ]
    assign_agent_roles(
        steps,
        operation="generate_report",
        tasks=[
            {"task_id": "task-1", "operation": {"name": "investment_opinion"}},
            {"task_id": "task-2", "operation": {"name": "portfolio_review"}},
        ],
    )
    roles = {step["name"]: step["inputs"]["role"] for step in steps}
    assert roles == {
        "news_agent": "support",
        "fundamental_agent": "lead",
        "risk_agent": "lead",
    }


def test_report_sections_are_attributed_and_lead_summary_is_first():
    state = {
        "output_mode": "investment_report",
        "subject": {"subject_type": "company", "tickers": ["AAPL"]},
        "policy": {"allowed_agents": ["news_agent", "fundamental_agent"]},
        "plan_ir": {
            "steps": [
                {
                    "id": "n1",
                    "kind": "agent",
                    "name": "news_agent",
                    "inputs": {"role": "support"},
                },
                {
                    "id": "f1",
                    "kind": "agent",
                    "name": "fundamental_agent",
                    "inputs": {"role": "lead"},
                },
            ]
        },
        "artifacts": {
            "draft_markdown": "## 投资研报：AAPL\n\n## 综合投资观点\n- 中性\n",
            "evidence_pool": [],
            "errors": [],
            "render_vars": {},
            "step_results": {
                "n1": {"output": {"summary": "新闻支持结论", "confidence": 0.7}},
                "f1": {"output": {"summary": "基本面主结论", "confidence": 0.8}},
            },
        },
        "trace": {},
    }

    report = build_report_payload(state=state, query="分析 AAPL", thread_id="lead-test")
    sections = report.get("sections") or []
    assert [section["title"] for section in sections[:2]] == [
        "基本面 · 基本面分析师",
        "新闻 · 舆情新闻分析师",
    ]

    markdown = str(report.get("synthesis_report") or "")
    lead_heading = "### 基本面 · 基本面分析师"
    support_heading = "### 新闻 · 舆情新闻分析师"
    assert lead_heading in markdown
    assert support_heading in markdown
    assert markdown.index(lead_heading) < markdown.index(support_heading)
    assert markdown.index("基本面主结论") < markdown.index("新闻支持结论")


def test_chat_agent_summary_uses_profile_attribution():
    state = {
        "plan_ir": {
            "steps": [
                {"id": "t1", "kind": "agent", "name": "technical_agent", "inputs": {}}
            ]
        },
        "artifacts": {
            "step_results": {
                "t1": {"output": {"summary": "短期动量转强"}},
            }
        },
    }

    assert _agent_summary(state, {"technical_agent"}) == "技术面分析师：短期动量转强"
