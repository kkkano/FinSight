# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import importlib

from backend.graph.nodes.research_debate import research_debate
from backend.graph.report_builder import build_report_payload


def _run(coro):
    return asyncio.run(coro)


def _state() -> dict:
    agents = ["fundamental_agent", "technical_agent", "news_agent"]
    steps = [
        {"id": f"s{index}", "kind": "agent", "name": name, "inputs": {}}
        for index, name in enumerate(agents, 1)
    ]
    results = {
        f"s{index}": {
            "output": {
                "summary": f"{name} 的核心判断包含具体数字 {index}",
                "evidence": [{"title": f"证据 {index}", "text": f"数据 {index}"}],
                "confidence": 0.7,
            }
        }
        for index, name in enumerate(agents, 1)
    }
    return {
        "query": "分析 NVDA 并生成投资报告",
        "output_mode": "investment_report",
        "subject": {"subject_type": "company", "tickers": ["NVDA"]},
        "policy": {"allowed_agents": agents},
        "plan_ir": {"steps": steps},
        "artifacts": {
            "draft_markdown": "## NVDA 投资报告\n\n## 综合投资观点\n- 谨慎乐观\n",
            "step_results": results,
            "evidence_pool": [],
            "errors": [],
            "render_vars": {},
        },
        "trace": {},
    }


def test_challenge_round_attaches_structured_objections_and_report_section(monkeypatch):
    async def fake_generate(_payload):
        return [
            {
                "target_agent": "technical_agent",
                "challenge_zh": "上涨结论是否忽略成交量较均值仅增加 3%？",
                "severity": "high",
            },
            {
                "target_agent": "fundamental_agent",
                "challenge_zh": "估值结论是否已计入下一季利润率回落风险？",
                "severity": "med",
            },
        ]

    monkeypatch.delenv("DEBATE_GRAPH_ENABLED", raising=False)
    debate_module = importlib.import_module("backend.graph.nodes.research_debate")
    monkeypatch.setattr(debate_module, "_generate_challenges", fake_generate)
    state = _state()
    result = _run(research_debate(state))
    debate = result["artifacts"]["debate"]
    assert debate["status"] == "done"
    assert len(debate["challenges"]) == 2
    assert debate["challenges"][0]["target_agent"] == "technical_agent"

    merged_state = dict(state)
    merged_state["artifacts"] = result["artifacts"]
    report = build_report_payload(
        state=merged_state,
        query=state["query"],
        thread_id="challenge-success",
    )
    markdown = str(report.get("synthesis_report") or "")
    assert "## 风险质询" in markdown
    assert "⚠ 对技术面分析师" in markdown
    assert "上涨结论是否忽略成交量" in markdown


def test_challenge_round_llm_failure_skips_without_blocking_report(monkeypatch):
    async def fail_generate(_payload):
        raise TimeoutError("challenge timeout")

    monkeypatch.setenv("DEBATE_GRAPH_ENABLED", "true")
    debate_module = importlib.import_module("backend.graph.nodes.research_debate")
    monkeypatch.setattr(debate_module, "_generate_challenges", fail_generate)
    state = _state()
    result = _run(research_debate(state))
    assert "debate" not in result["artifacts"]
    assert result["trace"]["research_debate"]["status"] == "skipped"

    merged_state = dict(state)
    merged_state["artifacts"] = result["artifacts"]
    report = build_report_payload(
        state=merged_state,
        query=state["query"],
        thread_id="challenge-failure",
    )
    assert "## 风险质询" not in str(report.get("synthesis_report") or "")
