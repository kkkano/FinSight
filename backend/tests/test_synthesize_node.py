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

    monkeypatch.setattr(llm_config_mod, "create_llm", lambda *args, **kwargs: _FakeLLM())

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

    monkeypatch.setattr(llm_config_mod, "create_llm", lambda *args, **kwargs: _FakeLLM())

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

    monkeypatch.setattr(llm_config_mod, "create_llm", lambda *args, **kwargs: _FakeLLM())

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


def test_sanitize_llm_section_flattens_json_lines():
    from backend.graph.nodes.synthesize import _sanitize_llm_section

    raw = """
{"event": "iPhone 17 AI 换机周期", "impact": "Q4 iPhone 营收增长 6%"}
{"risk": "技术面回调风险", "detail": "RSI > 80，短期存在均值回归压力"}
""".strip()

    out = _sanitize_llm_section(raw)

    assert "iPhone 17 AI 换机周期：Q4 iPhone 营收增长 6%" in out
    assert "技术面回调风险：RSI > 80，短期存在均值回归压力" in out
    assert "{" not in out and "}" not in out


def test_scrub_unverified_future_claims_removes_unsupported_release_claim():
    from backend.graph.nodes.synthesize import _scrub_unverified_future_claims

    draft = "预计2026Q2发布Gemini 2.0并推动广告业务增长。"
    evidence = "当前仅有PE 28.5与RSI 55等指标，无产品发布时间信息。"

    out = _scrub_unverified_future_claims(draft, evidence)

    assert "未经证据验证" in out
    assert "Gemini 2.0" not in out


def test_scrub_unverified_future_claims_keeps_claim_when_grounded():
    from backend.graph.nodes.synthesize import _scrub_unverified_future_claims

    draft = "预计2026Q2发布Gemini 2.0并推动广告业务增长。"
    evidence = "公司公告提到：预计2026Q2发布Gemini 2.0，用于广告产品。"

    out = _scrub_unverified_future_claims(draft, evidence)

    assert out == draft


def test_synthesize_llm_deep_research_applies_verifier_redaction(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_SYNTHESIZE_MODE", "llm")

    class _FakeResp:
        def __init__(self, content: str):
            self.content = content

    class _FakeLLM:
        async def ainvoke(self, _messages):
            return _FakeResp(
                '{"summary":"Gemini 2.0 will launch in 2026Q2.","conclusion":"Gemini 2.0 will launch in 2026Q2 and accelerate ad growth.","risks":"- risk"}'
            )

    import importlib
    import backend.llm_config as llm_config_mod
    synth_mod = importlib.import_module("backend.graph.nodes.synthesize")

    monkeypatch.setattr(llm_config_mod, "create_llm", lambda temperature=0.2, **_kwargs: _FakeLLM())

    async def _fake_verifier(*, state, generated_text, grounding_text):
        assert "Gemini 2.0 will launch in 2026Q2" in generated_text
        assert isinstance(grounding_text, str)
        return {
            "enabled": True,
            "checked": True,
            "unsupported_claims": [
                {"claim": "Gemini 2.0 will launch in 2026Q2", "reason": "missing evidence"}
            ],
        }

    monkeypatch.setattr(synth_mod, "_run_deep_report_verifier", _fake_verifier)

    state = {
        "query": "deep report on GOOG",
        "output_mode": "investment_report",
        "ui_context": {"analysis_depth": "deep_research"},
        "operation": {"name": "investment_report", "confidence": 0.8, "params": {}},
        "subject": {
            "subject_type": "company",
            "tickers": ["GOOG"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "artifacts": {"step_results": {}, "evidence_pool": []},
        "trace": {},
    }

    out = _run(synth_mod.synthesize(state))
    artifacts = out.get("artifacts") or {}
    render_vars = artifacts.get("render_vars") or {}
    conclusion = str(render_vars.get("conclusion") or "")

    assert "Gemini 2.0 will launch in 2026Q2" not in conclusion
    assert synth_mod._HALLUCINATION_SAFE_PLACEHOLDER in conclusion
    verifier = artifacts.get("verifier_result") or {}
    assert verifier.get("checked") is True
    assert len(verifier.get("unsupported_claims") or []) == 1
    assert len(verifier.get("unresolved_unsupported_claims") or []) == 0


def test_synthesize_narrative_persists_verifier_result(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_SYNTHESIZE_MODE", "narrative")

    import importlib
    synth_mod = importlib.import_module("backend.graph.nodes.synthesize")

    async def _fake_generate(_state, _render_vars, _trace):
        return (
            "## report\n\ncontent",
            {
                "enabled": True,
                "checked": True,
                "unsupported_claims": [{"claim": "c1", "reason": "r1"}],
            },
        )

    monkeypatch.setattr(synth_mod, "_generate_narrative_draft", _fake_generate)

    state = {
        "query": "investment report",
        "output_mode": "investment_report",
        "ui_context": {"analysis_depth": "deep_research"},
        "operation": {"name": "investment_report", "confidence": 0.8, "params": {}},
        "subject": {"subject_type": "company", "tickers": ["AAPL"]},
        "artifacts": {"step_results": {}, "evidence_pool": []},
        "trace": {},
    }

    out = _run(synth_mod.synthesize(state))
    artifacts = out.get("artifacts") or {}
    assert artifacts.get("draft_markdown")
    verifier = artifacts.get("verifier_result") or {}
    assert verifier.get("checked") is True
    assert len(verifier.get("unsupported_claims") or []) == 1


def test_compute_unresolved_unsupported_claims_returns_residual_claims():
    from backend.graph.nodes.synthesize import _compute_unresolved_unsupported_claims

    claims = [
        {"claim": "Claim A", "reason": "missing evidence"},
        {"claim": "Claim B", "reason": "missing evidence"},
    ]
    unresolved = _compute_unresolved_unsupported_claims(
        "This text still contains Claim B only.",
        claims,
    )
    assert len(unresolved) == 1
    assert unresolved[0]["claim"] == "Claim B"


# ========================================================================
# 2026-05-03 — Regression tests for "答非所问" fix.
# Mode-resolution rules in synthesize() entry:
#   - env=narrative + output_mode=brief         → downgrade to llm
#   - env=narrative + output_mode=investment_report → keep narrative
#   - report-mode tasks >= 2 (not pure compare) → force stub instead of narrative
# ========================================================================

def test_synthesize_narrative_downgraded_when_output_mode_brief(monkeypatch):
    """env=narrative + brief Q&A → must NOT trigger narrative LLM."""
    monkeypatch.setenv("LANGGRAPH_SYNTHESIZE_MODE", "narrative")

    import importlib
    synth_mod = importlib.import_module("backend.graph.nodes.synthesize")

    narrative_called = {"flag": False}

    async def _fake_generate(_state, _render_vars, _trace):
        narrative_called["flag"] = True
        return ("## should not be called\n\nbody", None)

    monkeypatch.setattr(synth_mod, "_generate_narrative_draft", _fake_generate)
    monkeypatch.setattr(synth_mod, "_run_deep_report_verifier", lambda **_kwargs: {"enabled": False, "checked": False})

    class _Resp:
        content = '{"conclusion":"MSFT 这次没有拿到实时价格证据，先按数据有限处理。"}'

    class _FakeLLM:
        async def ainvoke(self, _messages):
            return _Resp()

    async def _fake_retry(llm, messages, **_kwargs):
        return await llm.ainvoke(messages)

    monkeypatch.setattr(synth_mod, "ainvoke_with_rate_limit_retry", _fake_retry)

    import backend.llm_config as llm_config

    monkeypatch.setattr(llm_config, "create_llm", lambda **_kwargs: _FakeLLM())

    state = {
        "query": "今天微软什么价格",
        "output_mode": "brief",
        "operation": {"name": "price", "confidence": 0.8, "params": {}},
        "subject": {"subject_type": "company", "tickers": ["MSFT"]},
        "artifacts": {"step_results": {}, "evidence_pool": []},
        "trace": {},
    }

    out = _run(synth_mod.synthesize(state))
    assert narrative_called["flag"] is False, (
        "narrative LLM should NOT run for brief output_mode; "
        "expected compact LLM synthesis instead"
    )
    artifacts = out.get("artifacts") or {}
    assert "render_vars" in artifacts
    assert "draft_markdown" not in artifacts
    assert (out.get("trace") or {}).get("synthesize_runtime", {}).get("mode") == "llm"


def test_synthesize_llm_mode_uses_llm_for_non_price_chat_tasks(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_SYNTHESIZE_MODE", "llm")

    import importlib
    import backend.llm_config as llm_config

    synth_mod = importlib.import_module("backend.graph.nodes.synthesize")
    called = {"llm": False}

    class _FakeResp:
        content = '{"conclusion":"AAPL 最近新闻需要结合价格反应看。","impact_analysis":"先看新闻是否改变业绩预期。","risks":"- 数据有限"}'

    def _fake_create_llm(*_args, **_kwargs):
        called["llm"] = True
        return object()

    async def _fake_retry(*_args, **_kwargs):
        return _FakeResp()

    monkeypatch.setattr(llm_config, "create_llm", _fake_create_llm)
    monkeypatch.setattr(synth_mod, "ainvoke_with_rate_limit_retry", _fake_retry)

    state = {
        "query": "AAPL 最近新闻怎么看？",
        "output_mode": "chat",
        "operation": {"name": "fetch", "confidence": 0.8, "params": {"topic": "news"}},
        "subject": {"subject_type": "company", "tickers": ["AAPL"]},
        "tasks": [
            {
                "id": "task_1",
                "subject_type": "company",
                "tickers": ["AAPL"],
                "operation": {"name": "fetch", "confidence": 0.8, "params": {"topic": "news"}},
                "status": "ready",
            }
        ],
        "artifacts": {"step_results": {}, "evidence_pool": []},
        "trace": {},
    }

    out = _run(synth_mod.synthesize(state))
    runtime = (out.get("trace") or {}).get("synthesize_runtime") or {}
    assert called["llm"] is True
    assert runtime.get("mode") == "llm"
    assert runtime.get("fallback") is False
    assert "render_vars" in (out.get("artifacts") or {})


def test_synthesize_chat_preserves_natural_text_when_llm_ignores_json(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_SYNTHESIZE_MODE", "llm")

    import importlib
    import backend.llm_config as llm_config

    synth_mod = importlib.import_module("backend.graph.nodes.synthesize")

    class _FakeResp:
        content = "AAPL 先看价格；高估值怕利率，是因为折现率上行会压低远期现金流现值。最后关注利率预期和 MSFT 新闻是否影响云业务利润率。"

    async def _fake_retry(*_args, **_kwargs):
        return _FakeResp()

    monkeypatch.setattr(llm_config, "create_llm", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(synth_mod, "ainvoke_with_rate_limit_retry", _fake_retry)

    state = {
        "query": "AAPL 价格、MSFT 新闻、再解释一下为什么高估值怕利率，最后用一句话说我该关注什么。",
        "output_mode": "chat",
        "operation": {"name": "price", "confidence": 0.8, "params": {}},
        "subject": {"subject_type": "company", "tickers": ["AAPL", "MSFT"]},
        "tasks": [
            {"id": "task_1", "subject_type": "company", "tickers": ["AAPL"], "operation": {"name": "price"}},
            {"id": "task_2", "subject_type": "company", "tickers": ["MSFT"], "operation": {"name": "fetch"}},
            {"id": "task_3", "subject_type": "macro", "tickers": [], "operation": {"name": "analyze_impact"}},
        ],
        "artifacts": {"step_results": {}, "evidence_pool": []},
        "trace": {},
    }

    out = _run(synth_mod.synthesize(state))
    render_vars = (out.get("artifacts") or {}).get("render_vars") or {}
    runtime = (out.get("trace") or {}).get("synthesize") or {}
    assert runtime.get("natural_text") is True
    assert "折现率" in str(render_vars.get("conclusion") or "")
    assert "关注" in str(render_vars.get("conclusion") or "")


def test_synthesize_brief_router_task_graph_skips_llm_for_latency(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_SYNTHESIZE_MODE", "llm")

    import importlib
    import backend.llm_config as llm_config

    synth_mod = importlib.import_module("backend.graph.nodes.synthesize")
    called = {"llm": False}

    def _fake_create_llm(*_args, **_kwargs):
        called["llm"] = True
        raise AssertionError("brief router task graph should not call synthesis LLM")

    monkeypatch.setattr(llm_config, "create_llm", _fake_create_llm)

    state = {
        "query": "30秒告诉我 GOOGL 和 MSFT 今天谁更强",
        "output_mode": "brief",
        "operation": {"name": "compare", "confidence": 0.8, "params": {}},
        "subject": {"subject_type": "company", "tickers": ["GOOGL", "MSFT"]},
        "tasks": [
            {
                "id": "task_1",
                "subject_type": "company",
                "tickers": ["GOOGL"],
                "operation": {"name": "price"},
                "reason": "conversation_router_task_hint",
            },
            {
                "id": "task_2",
                "subject_type": "company",
                "tickers": ["MSFT"],
                "operation": {"name": "fetch"},
                "reason": "conversation_router_task_hint",
            },
        ],
        "artifacts": {"step_results": {}, "evidence_pool": []},
        "trace": {},
    }

    out = _run(synth_mod.synthesize(state))
    runtime = (out.get("trace") or {}).get("synthesize_runtime") or {}
    assert called["llm"] is False
    assert runtime.get("mode") == "stub"
    assert "render_vars" in (out.get("artifacts") or {})


def test_synthesize_narrative_kept_for_investment_report(monkeypatch):
    """env=narrative + output_mode=investment_report → narrative still runs."""
    monkeypatch.setenv("LANGGRAPH_SYNTHESIZE_MODE", "narrative")

    import importlib
    synth_mod = importlib.import_module("backend.graph.nodes.synthesize")

    async def _fake_generate(_state, _render_vars, _trace):
        return ("## report\n\ncontent", {"enabled": True, "checked": True})

    monkeypatch.setattr(synth_mod, "_generate_narrative_draft", _fake_generate)

    state = {
        "query": "生成 AAPL 投资研报",
        "output_mode": "investment_report",
        "operation": {"name": "investment_report", "confidence": 0.8, "params": {}},
        "subject": {"subject_type": "company", "tickers": ["AAPL"]},
        "artifacts": {"step_results": {}, "evidence_pool": []},
        "trace": {},
    }

    out = _run(synth_mod.synthesize(state))
    artifacts = out.get("artifacts") or {}
    assert artifacts.get("draft_markdown") == "## report\n\ncontent"


def test_synthesize_multi_task_forces_stub_even_with_narrative_env(monkeypatch):
    """
    Multi-task plan (>=2 tasks, not pure compare) must force stub mode so
    render_stub._build_multitask_markdown can render per-task sections.
    Fixes the C20 bug where 「小米和理想，CPI 影响吗」only rendered 理想.
    """
    monkeypatch.setenv("LANGGRAPH_SYNTHESIZE_MODE", "narrative")

    import importlib
    synth_mod = importlib.import_module("backend.graph.nodes.synthesize")

    narrative_called = {"flag": False}

    async def _fake_generate(_state, _render_vars, _trace):
        narrative_called["flag"] = True
        return ("## report\n\ncontent", None)

    monkeypatch.setattr(synth_mod, "_generate_narrative_draft", _fake_generate)

    state = {
        "query": "我老婆要我买基金，烦死了，对了帮我看下小米和理想汽车，CPI 影响吗",
        "output_mode": "investment_report",  # even with deep-report mode
        "operation": {"name": "analyze_impact", "confidence": 0.8, "params": {}},
        "subject": {"subject_type": "company", "tickers": ["XIACY"]},
        "tasks": [
            {
                "id": "task_1",
                "subject_type": "company",
                "tickers": ["XIACY"],
                "operation": {"name": "analyze_impact", "confidence": 0.8, "params": {}},
            },
            {
                "id": "task_2",
                "subject_type": "company",
                "tickers": ["LI"],
                "operation": {"name": "analyze_impact", "confidence": 0.8, "params": {}},
            },
            {
                "id": "task_3",
                "subject_type": "macro",
                "tickers": [],
                "operation": {"name": "analyze_impact", "confidence": 0.8, "params": {}},
            },
        ],
        "artifacts": {"step_results": {}, "evidence_pool": []},
        "trace": {},
    }

    out = _run(synth_mod.synthesize(state))
    assert narrative_called["flag"] is False, (
        "Multi-task plan must downgrade to stub so per-task sections are rendered; "
        "narrative cannot disambiguate multiple independent tickers"
    )
    artifacts = out.get("artifacts") or {}
    assert "render_vars" in artifacts
