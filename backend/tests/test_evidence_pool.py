# -*- coding: utf-8 -*-
import asyncio


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

