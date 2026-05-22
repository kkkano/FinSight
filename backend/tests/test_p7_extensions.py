# -*- coding: utf-8 -*-
from backend.graph.request_facets import derive_request_facets
from backend.graph.nodes.policy_gate import policy_gate
from backend.tools.python_compute import run_python_compute


def test_cn_research_skill_selects_for_a_share_research_but_not_price_only():
    subject = {"subject_type": "company", "tickers": ["600519.SS"]}
    operation = {"name": "qa", "confidence": 0.8, "params": {}}
    research_state = {
        "query": "贵州茅台 最近公告和财务情况怎么看",
        "operation": operation,
        "output_mode": "chat",
        "subject": subject,
        "facets": derive_request_facets(query="", operation=operation, subject=subject),
    }
    research_policy = policy_gate(research_state)["policy"]

    assert (research_policy.get("skill_selection") or {}).get("selected_skill") == "eastmoney-a-share-research"
    assert "get_local_market_filings" in research_policy.get("allowed_tools", [])
    assert "get_cn_market_fund_flow" in research_policy.get("allowed_tools", [])

    price_operation = {"name": "price", "confidence": 0.9, "params": {}}
    price_state = {
        **research_state,
        "query": "600519.SS 当前价格是多少",
        "operation": price_operation,
        "facets": derive_request_facets(query="", operation=price_operation, subject=subject),
    }
    price_policy = policy_gate(price_state)["policy"]

    assert (price_policy.get("skill_selection") or {}).get("selected_skill") is None


def test_python_compute_growth_chart_returns_svg_artifact():
    result = run_python_compute(
        dataset_refs=["step:get_sec_company_facts_quarterly"],
        operation="growth_chart",
        params={"metric": "revenue"},
        datasets={
            "step:get_sec_company_facts_quarterly": {
                "quarterly": [
                    {"period": "2025Q1", "revenue": 100.0},
                    {"period": "2025Q2", "revenue": 130.0},
                    {"period": "2025Q3", "revenue": 160.0},
                ]
            }
        },
    )

    assert result["charts"][0]["format"] == "svg"
    assert "<svg" in result["charts"][0]["svg"]
    assert result["charts"][0]["input_refs"] == ["step:get_sec_company_facts_quarterly"]


def test_thread_workspace_writes_and_reads_notes(tmp_path):
    from backend.workspace.thread_workspace import ThreadWorkspace

    workspace = ThreadWorkspace(root=tmp_path)
    note = workspace.append_note(thread_id="thread-1", content="NVDA valuation sanity checked.")

    assert note.path.name == "notes.md"
    assert "NVDA valuation" in workspace.read_notes("thread-1")
    assert note.thread_id == "thread-1"


def test_deepagents_bridge_requires_explicit_enablement():
    from backend.agents.deepagents_bridge import build_deepagents_context, should_use_deepagents

    facets = {"primary_task": "deep_research", "analysis_need": ["workspace", "multi_step"]}

    assert should_use_deepagents(facets, {"enable_deepagents": True}) is True
    assert should_use_deepagents(facets, {}) is False

    context = build_deepagents_context(facets, {"thread_id": "t-1", "enable_deepagents": True})
    assert context["enabled"] is True
    assert context["workspace_scope"] == "thread:t-1"
