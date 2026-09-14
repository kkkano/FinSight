# -*- coding: utf-8 -*-
"""WP3-T4 对拍守护：render_vars 拆分前后逐键相等（spec Step 2）。

基准 = tests/fixtures/render_vars_legacy._stub_render_vars_legacy（原函数逐字节冻结副本）；
输入 = 金样确定性 harness 的完整终态（覆盖 company/macro/news/doc/unknown 分支）。
"""
import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

_GOLDEN_CONFTEST = Path(__file__).resolve().parents[2] / "tests" / "golden" / "conftest.py"
_spec = importlib.util.spec_from_file_location("_golden_conftest", _GOLDEN_CONFTEST)
_golden = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_golden)
DETERMINISTIC_ENV = _golden.DETERMINISTIC_ENV

PARITY_QUERIES = {
    "single_report": "给我一份 NVDA 的投资分析",
    "multi_question": "对比 AAPL 和 MSFT 的估值，另外美联储下次议息是什么时候",
    "macro_only": "美国 CPI 最近走势怎么样",
    "news_impact": "TSLA 最近的新闻对股价有什么影响",
    "url_doc": "总结一下 https://example.com/a-16k-filing 的要点",
    "vague_no_subject": "帮我分析一下",
}

if sys.platform.startswith("win") and hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture()
def deterministic_env(monkeypatch):
    for key, value in DETERMINISTIC_ENV.items():
        monkeypatch.setenv(key, value)
    yield


def _run_full_state(query: str) -> dict:
    from backend.graph.runner import GraphRunner

    async def _run() -> dict:
        runner = GraphRunner.create()
        return await runner.ainvoke(
            thread_id=f"render-vars-parity-{abs(hash(query)) % 10_000}",
            query=query,
            ui_context={},
        )

    return asyncio.run(_run())


@pytest.mark.parametrize("name", sorted(PARITY_QUERIES))
def test_render_vars_parity(name, deterministic_env):
    from backend.graph.render_vars import build_render_vars
    from backend.tests.fixtures.render_vars_legacy import _stub_render_vars_legacy

    state = _run_full_state(PARITY_QUERIES[name])
    legacy = _stub_render_vars_legacy(state)
    new = build_render_vars(state)
    assert set(new) == set(legacy), f"key set drift: {set(new) ^ set(legacy)}"
    for key in legacy:
        assert new[key] == legacy[key], f"value drift at {key!r}"
