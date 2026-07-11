# -*- coding: utf-8 -*-
"""金样快照：LLM 关闭 + dry_run 下，管线对固定 query 的结构化输出必须逐字节稳定。

这是 WP2/WP3 全部重构任务的零行为变更防线（spec: 03-wp2 Task 0）。
"""
import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

SNAPSHOT_DIR = Path(__file__).parent / "snapshots"

DETERMINISTIC_ENV = {
    "LANGGRAPH_EXECUTE_LIVE_TOOLS": "false",   # executor dry-run
    "AGENT_LLM_ANALYZE_ENABLED": "false",
    "LANGGRAPH_PLANNER_AB_ENABLED": "false",
    "FINSIGHT_UNDERSTANDING_V2_MODE": "off",
    "DEBATE_GRAPH_ENABLED": "false",
    # LLM router 不可用 → 走确定性 fallback 路径（这正是我们要冻结的规则行为）
    "OPENAI_COMPATIBLE_API_KEY": "",
    "OPENAI_COMPATIBLE_API_BASE": "",
    "GRAPH_CHECKPOINT_BACKEND": "memory",
    # WP2 Task11 收尾：金样固定在新编排引擎（四 flag 全 on）。
    # LLM-off 下 on/off 切片逐字节一致（T3/T5 三模式对拍已证明），
    # 固定 on 让金样从此持续压测 IntentFrame 管线 + DAG 执行器路径。
    "FINSIGHT_INTENT_FRAME": "on",
    "FINSIGHT_DAG_EXECUTOR": "on",
    "FINSIGHT_AGENT_BRIEF": "on",
    "FINSIGHT_EVIDENCE_BUS": "on",
}

# Windows + asyncio.run：与 backend/api/main.py 相同的 event loop 策略
if sys.platform.startswith("win") and hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture()
def deterministic_env(monkeypatch):
    from backend.config.settings import clear_settings_caches

    for key, value in DETERMINISTIC_ENV.items():
        monkeypatch.setenv(key, value)
    clear_settings_caches()
    yield
    clear_settings_caches()


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


def run_pipeline_deterministic(query: str, ui_context: dict | None = None) -> dict:
    from backend.graph.runner import GraphRunner

    async def _run() -> dict:
        runner = GraphRunner.create()
        final_state = await runner.ainvoke(
            thread_id=f"golden-{abs(hash(query)) % 10_000}",
            query=query,
            ui_context=ui_context or {},
        )
        return _stable_slice(final_state)

    return asyncio.run(_run())


def assert_matches_snapshot(name: str, payload: dict) -> None:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOT_DIR / f"{name}.json"
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if os.getenv("GOLDEN_UPDATE") == "1" or not path.exists():
        path.write_text(rendered, encoding="utf-8")
        return
    assert path.read_text(encoding="utf-8") == rendered, (
        f"golden snapshot drift: {name}. 若 diff 是本任务预期行为变更，"
        f"用 GOLDEN_UPDATE=1 重录并在 commit message 里解释每一处 diff。"
    )
