# -*- coding: utf-8 -*-
"""RAG quality runner patch 必须命中 GraphRunner 实际绑定的节点。"""
from __future__ import annotations

from pathlib import Path


def test_graph_builder_resolves_execute_node_from_runner_patch(monkeypatch) -> None:
    import backend.graph.runner as runner_module

    captured: dict[str, object] = {}

    async def injected_execute(_state):
        return {"artifacts": {"evidence_pool": [{"title": "fixture"}]}, "trace": {}}

    original_with_trace = runner_module.with_node_trace

    def capture_with_trace(name, node):
        if name == "execute_plan":
            captured["node"] = node
        return original_with_trace(name, node)

    monkeypatch.setattr(runner_module, "execute_plan_node", injected_execute)
    monkeypatch.setattr(runner_module, "with_node_trace", capture_with_trace)
    runner_module._build_graph(checkpointer=None)

    assert captured["node"] is injected_execute


def test_rag_quality_scripts_patch_runner_binding() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    scripts = (
        "tests/rag_quality/run_layer3_e2e.py",
        "tests/rag_quality/debug_layer3_single.py",
        "tests/rag_qualityV2/run_layer3_v2.py",
    )

    for relative in scripts:
        source = (repo_root / relative).read_text(encoding="utf-8-sig")
        assert '"backend.graph.runner.execute_plan_node"' in source, relative
        assert '"backend.graph.nodes.execute_plan_node.execute_plan_node"' not in source, relative
