# -*- coding: utf-8 -*-
"""规则降级金样与显式语义 fixture；不依赖外部模型或供应商。"""
import asyncio
import json
import sys
from pathlib import Path

import pytest

SNAPSHOT_DIR = Path(__file__).parent / "snapshots"

DETERMINISTIC_ENV = {
    "LANGGRAPH_EXECUTE_LIVE_TOOLS": "false",   # executor dry-run
    "LANGGRAPH_SYNTHESIZE_MODE": "stub",
    "LANGGRAPH_PLANNER_AB_ENABLED": "false",
    "FINSIGHT_UNDERSTANDING_V2_MODE": "off",
    "DEBATE_GRAPH_ENABLED": "false",
    # LLM router 不可用 → 走确定性 fallback 路径（这正是我们要冻结的规则行为）
    "OPENAI_COMPATIBLE_API_KEY": "",
    "OPENAI_COMPATIBLE_API_BASE": "",
    "GRAPH_CHECKPOINT_BACKEND": "memory",
    "LANGGRAPH_CHECKPOINTER_BACKEND": "memory",
    "LANGGRAPH_CHECKPOINTER_ALLOW_MEMORY_FALLBACK": "true",
    "FINSIGHT_RUNTIME_PROFILE": "test",
    "FINSIGHT_LLM_REQUIRED": "false",
    # WP2 Task11 收尾：金样固定在新编排引擎（四 flag 全 on）。
    # LLM-off 下 on/off 切片逐字节一致（T3/T5 三模式对拍已证明），
    # 固定 on 让金样从此持续压测 IntentFrame 管线 + DAG 执行器路径。
    "FINSIGHT_INTENT_FRAME": "on",
}

# Windows + asyncio.run：与 backend/api/main.py 相同的 event loop 策略
if sys.platform.startswith("win") and hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture()
def deterministic_env(monkeypatch):
    from backend.config.settings import clear_settings_caches
    from importlib import import_module

    async def disabled_semantic_model(*_args, **_kwargs):
        return None, {"status": "unconfirmed", "cause_code": "llm_disabled_for_golden"}

    monkeypatch.setattr(import_module("backend.graph.nodes.route_request"), "extract_semantic_requirements", disabled_semantic_model)
    model_calls = []

    async def forbidden_direct_model(*_args, **_kwargs):
        model_calls.append("direct_answer")
        raise AssertionError("golden 禁止真实模型调用")

    monkeypatch.setattr(import_module("backend.graph.nodes.analyze"), "ainvoke_configured_llm", forbidden_direct_model)

    for key, value in DETERMINISTIC_ENV.items():
        monkeypatch.setenv(key, value)
    clear_settings_caches()
    yield
    clear_settings_caches()
    assert model_calls == [], "纯规则金样不应进入需模型作答的概念分支"


@pytest.fixture()
def confirmed_semantic_env(monkeypatch, deterministic_env):
    from importlib import import_module
    from backend.tests.semantic_request_fixtures import _request, fixture_for_query

    explicit_cases = {
        "AAPL 现在多少钱": ([(["AAPL"], ["quote"])], {}),
        "对比 AAPL 和 MSFT 的估值": ([(["AAPL", "MSFT"], ["valuation_reasonableness"])], {"relation": "compare"}),
        "600036 走势如何": ([(["600036.SS"], ["trend_quality"])], {}),
    }

    async def confirmed_model_output(state, seed):
        query = str(state.get("query") or "")
        if query in explicit_cases:
            groups, options = explicit_cases[query]
            semantic = _request(query, groups, **options)
        else:
            semantic = fixture_for_query(query, state=state, seed=seed)
        if query == "给我一份 NVDA 的投资分析":
            semantic["output_mode"] = "investment_report"
        return semantic, {"status": "confirmed", "source": "explicit_test_fixture", "actual_model": "fixture-model"}

    monkeypatch.setattr(import_module("backend.graph.nodes.route_request"), "extract_semantic_requirements", confirmed_model_output)


def _stable_slice(final_state: dict) -> dict:
    """抽取与时间/随机无关的结构切片。"""
    understanding = final_state.get("understanding") or {}
    plan_ir = final_state.get("plan_ir") or {}
    return {
        "route": understanding.get("route"),
        "tasks": [
            {
                "subject_type": t.get("subject_type"),
                "tickers": t.get("tickers"),
                "operation": (t.get("operation") or {}).get("name"),
                "reason": t.get("reason"),
            }
            for t in (understanding.get("tasks") or [])
        ],
        "blocked_reasons": [b.get("reason") for b in (understanding.get("blocked_tasks") or [])],
        "plan_steps": [
            {"kind": s.get("kind"), "name": s.get("name"), "group": s.get("parallel_group")}
            for s in (plan_ir.get("steps") or [])
        ],
        "output_mode": final_state.get("output_mode"),
    }


def run_pipeline_deterministic(query: str, ui_context: dict | None = None, *, full_state: bool = False) -> dict:
    from backend.graph.runner import GraphRunner

    async def _run() -> dict:
        runner = GraphRunner.create()
        final_state = await runner.ainvoke(
            thread_id=f"golden-{abs(hash(query)) % 10_000}",
            query=query,
            ui_context=ui_context or {},
        )
        return final_state if full_state else _stable_slice(final_state)

    return asyncio.run(_run())


def assert_matches_snapshot(name: str, payload: dict) -> None:
    path = SNAPSHOT_DIR / f"{name}.json"
    assert path.exists(), f"missing golden snapshot: {name}"
    assert json.loads(path.read_text(encoding="utf-8")) == payload, (
        f"golden snapshot drift: {name}. 先逐项核对业务变化与合同，再手工更新已审阅快照。"
    )
