# -*- coding: utf-8 -*-
import asyncio
from datetime import datetime, timezone


def _run(coro):
    return asyncio.run(coro)


def test_synthesize_llm_mode_handles_datetime_in_inputs(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_SYNTHESIZE_MODE", "llm")

    class _FakeResp:
        def __init__(self, content: str):
            self.content = content

    class _FakeLLM:
        async def ainvoke(self, _messages):
            return _FakeResp('{"summary":"ok","risks":"- r"}')

    import backend.llm_config as llm_config_mod

    monkeypatch.setattr(llm_config_mod, "create_llm", lambda temperature=0.2: _FakeLLM())

    from backend.graph.nodes.synthesize import synthesize

    state = {
        "query": "NVDA 最新股价和技术面分析",
        "output_mode": "brief",
        "operation": {"name": "company_news_brief", "confidence": 0.8, "params": {}},
        "subject": {"subject_type": "company", "tickers": ["NVDA"], "selection_payload": []},
        "artifacts": {
            "step_results": {
                "s1": {
                    "cached": False,
                    "output": {
                        "as_of": datetime(2026, 2, 7, 21, 47, 39, tzinfo=timezone.utc),
                        "price": 132.6,
                    },
                }
            },
            "evidence_pool": [],
        },
        "trace": {},
    }

    out = _run(synthesize(state))
    render_vars = (out.get("artifacts") or {}).get("render_vars") or {}
    assert isinstance(render_vars, dict) and render_vars


def test_synthesize_stub_produces_render_vars_without_placeholders(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_SYNTHESIZE_MODE", "stub")

    from backend.graph.nodes.synthesize import synthesize

    state = {
        "query": "分析影响",
        "output_mode": "brief",
        "operation": {"name": "analyze_impact", "confidence": 0.7, "params": {}},
        "subject": {
            "subject_type": "news_item",
            "tickers": [],
            "selection_ids": ["n1"],
            "selection_types": ["news"],
            "selection_payload": [{"type": "news", "id": "n1", "title": "t", "snippet": "s"}],
        },
        "artifacts": {
            "evidence_pool": [{"title": "t", "url": None, "snippet": "s", "source": "x", "published_date": "2026-02-03"}]
        },
        "trace": {},
    }

    out = _run(synthesize(state))
    artifacts = out.get("artifacts") or {}
    render_vars = artifacts.get("render_vars") or {}
    assert isinstance(render_vars, dict) and render_vars

    assert render_vars.get("news_summary")
    assert render_vars.get("impact_analysis")

    for v in render_vars.values():
        assert "待实现" not in str(v)


def test_synthesize_llm_mode_includes_compare_keys_and_preserves_stub_defaults(monkeypatch):
    """
    Regression: when LANGGRAPH_SYNTHESIZE_MODE=llm, the LLM may omit compare-specific keys.
    We must (a) expose compare keys in the prompt schema and (b) fall back to stub defaults
    so the compare template never renders placeholder sections.
    """
    monkeypatch.setenv("LANGGRAPH_SYNTHESIZE_MODE", "llm")

    captured: dict[str, str] = {}

    class _FakeResp:
        def __init__(self, content: str):
            self.content = content

    class _FakeLLM:
        async def ainvoke(self, messages):
            captured["prompt"] = messages[0].content
            # LLM may omit compare keys or (worse) hallucinate metrics; we should preserve stub data sections.
            return _FakeResp('{"risks": "- risk from llm", "comparison_metrics": "PE 31x vs 35x"}')

    import backend.llm_config as llm_config_mod

    monkeypatch.setattr(llm_config_mod, "create_llm", lambda temperature=0.2: _FakeLLM())

    from backend.graph.nodes.synthesize import synthesize

    state = {
        "query": "Compare AAPL vs MSFT",
        "output_mode": "brief",
        "operation": {"name": "compare", "confidence": 0.8, "params": {}},
        "subject": {
            "subject_type": "company",
            "tickers": ["AAPL", "MSFT"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "plan_ir": {
            "steps": [
                {
                    "id": "s1",
                    "kind": "tool",
                    "name": "get_performance_comparison",
                    "inputs": {"tickers": {"AAPL": "AAPL", "MSFT": "MSFT"}},
                    "optional": False,
                }
            ]
        },
        "artifacts": {
            "step_results": {
                "s1": {
                    "cached": False,
                    "output": "Performance Comparison:\\nAAPL ...\\nMSFT ...\\n",
                }
            },
            "evidence_pool": [],
        },
        "trace": {},
    }

    out = _run(synthesize(state))
    artifacts = out.get("artifacts") or {}
    render_vars = artifacts.get("render_vars") or {}

    assert "comparison_conclusion" in captured.get("prompt", "")
    assert "comparison_metrics" in captured.get("prompt", "")

    assert "AAPL" in str(render_vars.get("comparison_conclusion") or "")
    assert "PE 31x" not in str(render_vars.get("comparison_metrics") or "")
    risks = str(render_vars.get("risks") or "")
    assert "risk from llm" in risks
    assert "不构成投资建议" in risks


def test_synthesize_stub_compare_parses_label_rows_via_step_input_mapping(monkeypatch):
    """
    Regression: planner may call get_performance_comparison with a label->ticker mapping,
    producing a table with "Apple/Microsoft" rows. Synthesize must still emit explicit
    YTD/1Y compare lines for tickers (AAPL/MSFT).
    """
    monkeypatch.setenv("LANGGRAPH_SYNTHESIZE_MODE", "stub")

    from backend.graph.nodes.synthesize import synthesize

    state = {
        "query": "对比 AAPL 和 MSFT 哪个更值得投资",
        "output_mode": "brief",
        "operation": {"name": "compare", "confidence": 0.8, "params": {}},
        "subject": {
            "subject_type": "company",
            "tickers": ["AAPL", "MSFT"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "plan_ir": {
            "steps": [
                {
                    "id": "s1",
                    "kind": "tool",
                    "name": "get_performance_comparison",
                    "inputs": {"tickers": {"Apple": "AAPL", "Microsoft": "MSFT"}},
                    "optional": False,
                }
            ]
        },
        "artifacts": {
            "step_results": {
                "s1": {
                    "cached": False,
                    "output": (
                        "Performance Comparison:\n\n"
                        "Ticker                    Current Price   YTD %        1-Year %\n"
                        "-------------------------------------------------------------------\n"
                        "Apple                     269.48          -0.56%       +15.92%\n"
                        "Microsoft                 411.21          -13.05%      -0.50%\n\n"
                        "Notes:\n"
                        "- Apple: used fallback price history\n"
                        "- Microsoft: used fallback price history\n"
                    ),
                }
            },
            "evidence_pool": [],
        },
        "trace": {},
    }

    out = _run(synthesize(state))
    artifacts = out.get("artifacts") or {}
    render_vars = artifacts.get("render_vars") or {}
    conclusion = str(render_vars.get("comparison_conclusion") or "")
    metrics = str(render_vars.get("comparison_metrics") or "")

    assert "结论（历史回报维度）" in conclusion and "AAPL" in conclusion and "MSFT" in conclusion
    assert "YTD：" in metrics and "AAPL" in metrics and "MSFT" in metrics
    assert "-0.56%" in metrics and "-13.05%" in metrics
    assert "1Y：" in metrics and "+15.92%" in metrics and "-0.50%" in metrics


def test_synthesize_stub_company_fetch_formats_news_summary(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_SYNTHESIZE_MODE", "stub")

    from backend.graph.nodes.synthesize import synthesize

    state = {
        "query": "特斯拉最近有什么重大新闻",
        "output_mode": "brief",
        "operation": {"name": "fetch", "confidence": 0.7, "params": {}},
        "subject": {
            "subject_type": "company",
            "tickers": ["TSLA"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "plan_ir": {
            "steps": [
                {
                    "id": "s1",
                    "kind": "tool",
                    "name": "get_company_news",
                    "inputs": {"ticker": "TSLA"},
                    "optional": True,
                }
            ]
        },
        "artifacts": {
            "step_results": {
                "s1": {
                    "cached": False,
                    "output": '[{"title":"Tesla update","url":"https://example.com/a","source":"x","published_at":"2026-02-04"}]',
                }
            },
            "evidence_pool": [],
        },
        "trace": {"executor": {"type": "live_tools"}},
    }

    out = _run(synthesize(state))
    artifacts = out.get("artifacts") or {}
    render_vars = artifacts.get("render_vars") or {}
    news_summary = str(render_vars.get("news_summary") or "")
    conclusion = str(render_vars.get("conclusion") or "")

    assert "[Tesla update](https://example.com/a)" in news_summary
    assert "你想先看哪一条" in conclusion


def test_synthesize_llm_mode_formats_risks_dict(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_SYNTHESIZE_MODE", "llm")

    class _FakeResp:
        def __init__(self, content: str):
            self.content = content

    class _FakeLLM:
        async def ainvoke(self, messages):
            return _FakeResp(
                '{"risks": {"AAPL": "r1", "MSFT": "r2", "disclaimer": "past performance..."}}'
            )

    import backend.llm_config as llm_config_mod

    monkeypatch.setattr(llm_config_mod, "create_llm", lambda temperature=0.2: _FakeLLM())

    from backend.graph.nodes.synthesize import synthesize

    state = {
        "query": "Compare AAPL vs MSFT",
        "output_mode": "brief",
        "operation": {"name": "compare", "confidence": 0.8, "params": {}},
        "subject": {
            "subject_type": "company",
            "tickers": ["AAPL", "MSFT"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "artifacts": {"step_results": {}, "evidence_pool": []},
        "trace": {},
    }

    out = _run(synthesize(state))
    artifacts = out.get("artifacts") or {}
    render_vars = artifacts.get("render_vars") or {}
    risks = str(render_vars.get("risks") or "")

    assert "AAPL" in risks and "MSFT" in risks
    assert "{" not in risks and "}" not in risks
    assert "不构成投资建议" in risks
