from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_CALLSITES = (
    "backend/graph/intent/router.py",
    "backend/graph/nodes/planner.py",
    "backend/graph/nodes/synthesize.py",
    "backend/graph/nodes/research_debate.py",
    "backend/graph/adapters/agent_adapter.py",
    "backend/agents/base_agent.py",
    "backend/agents/deep_search_agent.py",
    "backend/agents/news_agent.py",
    "backend/services/monitor_commentator.py",
    "backend/api/chart_intelligence.py",
    "backend/dashboard/scorers.py",
    "backend/graph/nodes/resolve_subject.py",
    "backend/graph/synthesis/narrative.py",
    "backend/report/verifier.py",
    "backend/services/monitor_l2.py",
    "backend/services/rebalance_llm_enhancer.py",
    "backend/api/app_factory.py",
)


def _attribute_name(node: ast.AST) -> str | None:
    return node.attr if isinstance(node, ast.Attribute) else None


def test_production_llm_callsites_use_the_unified_entry() -> None:
    violations: list[str] = []
    for relative_path in PRODUCTION_CALLSITES:
        path = ROOT / relative_path
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=relative_path)
        if "ainvoke_with_rate_limit_retry" in source:
            violations.append(f"{relative_path}: legacy retry helper")
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            attribute = _attribute_name(node.func)
            if attribute in {"astream", "invoke"}:
                violations.append(f"{relative_path}:{node.lineno}: raw {attribute}")
            if attribute == "ainvoke" and relative_path != "backend/services/monitor_commentator.py":
                violations.append(f"{relative_path}:{node.lineno}: raw ainvoke")
        if any(token in source for token in ("create_llm(", "create_llm as")):
            violations.append(f"{relative_path}: client created before endpoint selection")

    assert violations == []


def test_only_retry_module_invokes_provider_client_directly() -> None:
    retry_source = (ROOT / "backend/services/llm_retry.py").read_text(encoding="utf-8")
    assert "invoke=lambda client, payload: client.ainvoke(payload)" in retry_source
