# -*- coding: utf-8 -*-
import asyncio
import copy

from backend.graph.execution.evidence_pipeline import normalize_execution_evidence


def _run(coro):
    return asyncio.run(coro)


def test_evidence_pool_built_from_selection_payload():
    from backend.graph import GraphRunner

    runner = GraphRunner.create()
    ui_context = {
        "selections": [
            {
                "type": "news",
                "id": "n1",
                "title": "Hello",
                "url": "https://example.com",
                "snippet": "snippet",
                "source": "unit",
                "ts": "2026-02-02",
            }
        ]
    }
    result = _run(runner.ainvoke(thread_id="t-evi", query="分析影响", ui_context=ui_context))
    artifacts = result.get("artifacts") or {}
    pool = artifacts.get("evidence_pool") or []
    assert isinstance(pool, list) and pool
    assert pool[0].get("title") == "Hello"


def test_shared_url_keeps_all_task_and_step_provenance(monkeypatch):
    monkeypatch.setenv("JINA_ENRICH_EVIDENCE", "false")
    shared_url = "https://example.com/shared-report"
    plan_ir = {
        "steps": [
            {"id": "step-a", "kind": "agent", "name": "news_agent", "task_ids": ["task-a"]},
            {"id": "step-b", "kind": "agent", "name": "news_agent", "task_ids": ["task-b"]},
        ]
    }
    artifacts = {
        "step_results": {
            "step-a": {
                "output": {
                    "evidence": [
                        {"title": "Shared report", "text": "Evidence for A", "url": shared_url}
                    ]
                }
            },
            "step-b": {
                "output": {
                    "evidence": [
                        {"title": "Shared report", "text": "Evidence for B", "url": shared_url}
                    ]
                }
            },
        }
    }

    evidence_pool, _step_index, _input_count = normalize_execution_evidence(
        state={"subject": {}},
        plan_ir=plan_ir,
        artifacts=artifacts,
    )

    shared = [item for item in evidence_pool if item.get("url") == shared_url]
    assert len(shared) == 1
    assert shared[0]["task_ids"] == ["task-a", "task-b"]
    assert shared[0]["step_ids"] == ["step-a", "step-b"]
    assert artifacts["evidence_by_task"]["task-a"][0]["url"] == shared_url
    assert artifacts["evidence_by_task"]["task-b"][0]["url"] == shared_url


def test_no_url_dedupe_keeps_same_title_sources_with_different_content(monkeypatch):
    monkeypatch.setenv("JINA_ENRICH_EVIDENCE", "false")
    artifacts = {
        "evidence_pool": [
            {
                "title": "news_agent summary",
                "source": "news_agent",
                "snippet": "A-specific summary",
                "task_ids": ["task-a"],
            },
            {
                "title": "news_agent summary",
                "source": "news_agent",
                "snippet": "B-specific summary",
                "task_ids": ["task-b"],
            },
        ]
    }

    evidence_pool, _step_index, _input_count = normalize_execution_evidence(
        state={"subject": {}},
        plan_ir={"steps": []},
        artifacts=artifacts,
    )

    assert [item["snippet"] for item in evidence_pool] == [
        "A-specific summary",
        "B-specific summary",
    ]
    assert artifacts["evidence_by_task"]["task-a"][0]["snippet"] == "A-specific summary"
    assert artifacts["evidence_by_task"]["task-b"][0]["snippet"] == "B-specific summary"


def test_shared_url_dedupe_does_not_mutate_inputs_or_alias_task_buckets(monkeypatch):
    monkeypatch.setenv("JINA_ENRICH_EVIDENCE", "false")
    shared_url = "https://example.com/shared-immutable"
    input_evidence = [
        {
            "title": "Shared immutable source",
            "url": shared_url,
            "source": "fixture",
            "task_ids": ["task-a"],
        },
        {
            "title": "Shared immutable source",
            "url": shared_url,
            "source": "fixture",
            "task_ids": ["task-b"],
        },
    ]
    original = copy.deepcopy(input_evidence)
    artifacts = {"evidence_pool": input_evidence}

    evidence_pool, _step_index, _input_count = normalize_execution_evidence(
        state={"subject": {}},
        plan_ir={"steps": []},
        artifacts=artifacts,
    )

    assert input_evidence == original
    assert len(evidence_pool) == 1
    task_a_item = artifacts["evidence_by_task"]["task-a"][0]
    task_b_item = artifacts["evidence_by_task"]["task-b"][0]
    assert task_a_item is not task_b_item
    task_a_item["title"] = "task A mutation"
    assert task_b_item["title"] == "Shared immutable source"
