# -*- coding: utf-8 -*-
import asyncio


def _run(coro):
    return asyncio.run(coro)


def test_url_turn_builds_source_grounded_contract_and_url_task():
    from backend.graph.nodes.understand_request import understand_request

    result = _run(
        understand_request(
            {
                "query": "Please read https://example.com/nvda and explain the market impact.",
                "output_mode": "chat",
                "ui_context": {},
                "trace": {},
            }
        )
    )

    contract = result.get("reply_contract") or {}
    assert contract.get("lane") == "source_grounded_answer"
    assert contract.get("citation_policy") == "must_cite_or_disclose_unavailable"
    assert contract.get("source_constraints", {}).get("requires_url_fetch") is True
    assert any(
        (task.get("operation") or {}).get("params", {}).get("url") == "https://example.com/nvda"
        for task in result.get("tasks") or []
    )


def test_url_turn_with_error_boundary_wording_still_plans_url_fetch():
    from backend.graph.nodes.understand_request import understand_request

    result = _run(
        understand_request(
            {
                "query": "If a source is blocked, do not treat the error as evidence. Read https://example.com/blocked-aapl.",
                "output_mode": "chat",
                "ui_context": {},
                "trace": {},
            }
        )
    )

    contract = result.get("reply_contract") or {}
    assert contract.get("lane") == "source_grounded_answer"
    assert contract.get("source_constraints", {}).get("requires_url_fetch") is True
    assert any(
        (task.get("operation") or {}).get("params", {}).get("url") == "https://example.com/blocked-aapl"
        for task in result.get("tasks") or []
    )


def test_selected_url_context_builds_grounded_fetch_plan(monkeypatch):
    import importlib

    from backend.graph.nodes.conversation_router import ContextBinding, ConversationDecision
    from backend.graph.nodes.planner_stub import planner_stub
    from backend.graph.nodes.policy_gate import policy_gate

    understand_mod = importlib.import_module("backend.graph.nodes.understand_request")

    async def fake_route_conversation(_state, *, tickers, selection_ids):
        assert selection_ids == ["goog-url"]
        return ConversationDecision(
            execution_route="research",
            context_binding=ContextBinding(
                source="selection",
                subject_hint="GOOGL selected URL",
                confidence=0.95,
            ),
            relation="new_topic",
            domain_intent="analysis",
            confidence=0.9,
            needs_tools=True,
        )

    monkeypatch.setattr(understand_mod, "route_conversation", fake_route_conversation)

    query = "This selected URL looks important; analyze it."
    result = _run(
        understand_mod.understand_request(
            {
                "query": query,
                "output_mode": "chat",
                "ui_context": {
                    "active_symbol": "GOOGL",
                    "view": "dashboard",
                    "selections": [
                        {
                            "type": "url",
                            "id": "goog-url",
                            "title": "Google AI update",
                            "url": "https://example.com/googl-ai",
                            "source": "eval",
                            "snippet": "Google released a model update.",
                        }
                    ],
                },
                "trace": {},
            }
        )
    )

    contract = result.get("reply_contract") or {}
    assert contract.get("lane") == "source_grounded_answer"
    assert contract.get("source_constraints", {}).get("requires_url_fetch") is True
    assert result.get("subject", {}).get("tickers") == ["GOOGL"]

    state = {"query": query, **result}
    state = {**state, **policy_gate(state)}
    plan = planner_stub(state)["plan_ir"]
    assert ("fetch_url_content", {"url": "https://example.com/googl-ai", "max_length": 6000}) in [
        (step.get("name"), step.get("inputs")) for step in plan.get("steps") or []
    ]


def test_quote_plus_headline_link_keeps_news_task(monkeypatch):
    import importlib

    from backend.graph.nodes.conversation_router import ContextBinding, ConversationDecision

    understand_mod = importlib.import_module("backend.graph.nodes.understand_request")

    async def fake_route_conversation(_state, *, tickers, selection_ids):
        return ConversationDecision(
            execution_route="research",
            context_binding=ContextBinding(source="none", subject_hint=", ".join(tickers)),
            relation="new_topic",
            domain_intent="quote",
            confidence=0.95,
            needs_tools=True,
            task_hints=(
                {
                    "subject_type": "company",
                    "subject_label": "NVDA",
                    "tickers": ["NVDA"],
                    "operation": "price",
                },
            ),
        )

    monkeypatch.setattr(understand_mod, "route_conversation", fake_route_conversation)

    result = _run(
        understand_mod.understand_request(
            {
                "query": "For NVDA, give price now and the latest headline link.",
                "output_mode": "chat",
                "ui_context": {},
                "trace": {},
            }
        )
    )

    operation_names = [
        (task.get("operation") or {}).get("name")
        for task in result.get("tasks") or []
    ]
    assert "price" in operation_names
    assert "fetch" in operation_names
    assert result.get("reply_contract", {}).get("source_constraints", {}).get("requires_links") is True


def test_report_mode_builds_report_generation_contract():
    from backend.graph.nodes.understand_request import understand_request

    result = _run(
        understand_request(
            {
                "query": "Generate an investment report for AAPL.",
                "output_mode": "investment_report",
                "ui_context": {},
                "trace": {},
            }
        )
    )

    contract = result.get("reply_contract") or {}
    assert contract.get("lane") == "report_generation"
    assert contract.get("answer_style") == "investment_report"
    assert contract.get("citation_policy") == "must_cite_or_disclose_unavailable"
    assert result.get("output_mode") == "investment_report"


def test_query_only_deep_report_upgrades_chat_default_to_report_generation(monkeypatch):
    import importlib

    from backend.graph.nodes.conversation_router import ContextBinding, ConversationDecision

    understand_mod = importlib.import_module("backend.graph.nodes.understand_request")
    calls = {"router": 0}

    async def fake_route_conversation(_state, *, tickers, selection_ids):
        calls["router"] += 1
        return ConversationDecision(
            execution_route="research",
            context_binding=ContextBinding(source="none", subject_hint=", ".join(tickers)),
            relation="new_topic",
            domain_intent="analysis",
            confidence=0.9,
            needs_tools=True,
        )

    monkeypatch.setattr(understand_mod, "route_conversation", fake_route_conversation)

    result = _run(
        understand_mod.understand_request(
            {
                "query": "请做 INTC 深度投资报告（deep report, filing document longform），重点引用 10-K/10-Q、业绩电话会与权威媒体来源，并给出明确结论与风险清单",
                "output_mode": "chat",
                "ui_context": {},
                "trace": {},
            }
        )
    )

    contract = result.get("reply_contract") or {}
    assert result.get("output_mode") == "investment_report"
    assert contract.get("lane") == "report_generation"
    assert contract.get("answer_style") == "investment_report"
    assert (result.get("understanding") or {}).get("route") == "research"
    assert calls["router"] == 0


def test_negated_report_trigger_stays_chat_mode():
    from backend.graph.nodes.decide_output_mode import decide_output_mode

    result = decide_output_mode({"query": "Do not generate a report; just summarize the three risks for AAPL."})

    assert result["output_mode"] == "chat"


def test_do_not_generate_report_turn_builds_chat_contract(monkeypatch):
    import importlib

    from backend.graph.nodes.conversation_router import ContextBinding, ConversationDecision

    understand_mod = importlib.import_module("backend.graph.nodes.understand_request")

    async def fake_route_conversation(_state, *, tickers, selection_ids):
        return ConversationDecision(
            execution_route="direct_answer",
            context_binding=ContextBinding(source="none", subject_hint=", ".join(tickers)),
            relation="new_topic",
            domain_intent="analysis",
            confidence=0.9,
            needs_tools=False,
        )

    async def fake_generate_contextual_reply(_state, _decision):
        return "AAPL has three main risk buckets: demand, margins, and valuation."

    monkeypatch.setattr(understand_mod, "route_conversation", fake_route_conversation)
    monkeypatch.setattr(understand_mod, "generate_contextual_reply", fake_generate_contextual_reply)

    result = _run(
        understand_mod.understand_request(
            {
                "query": "Do not generate a report; just summarize the three risks for AAPL.",
                "ui_context": {},
                "trace": {},
            }
        )
    )

    assert result["output_mode"] == "chat"
    assert result["reply_contract"]["lane"] == "chat_answer"
    assert result["chat_responded"] is True


def test_do_not_look_up_news_stays_chat_without_tasks(monkeypatch):
    import importlib

    from backend.graph.nodes.conversation_router import ContextBinding, ConversationDecision

    understand_mod = importlib.import_module("backend.graph.nodes.understand_request")

    async def fake_route_conversation(_state, *, tickers, selection_ids):
        return ConversationDecision(
            execution_route="direct_answer",
            context_binding=ContextBinding(source="none"),
            relation="new_topic",
            domain_intent="analysis",
            confidence=0.9,
            needs_tools=False,
        )

    async def fake_generate_contextual_reply(_state, _decision):
        return "Semiconductors can sell off together when investors de-risk the whole group."

    monkeypatch.setattr(understand_mod, "route_conversation", fake_route_conversation)
    monkeypatch.setattr(understand_mod, "generate_contextual_reply", fake_generate_contextual_reply)

    result = _run(
        understand_mod.understand_request(
            {
                "query": "Do not look up news. Just tell me why semiconductors can sell off together.",
                "ui_context": {},
                "trace": {},
            }
        )
    )

    assert result["reply_contract"]["lane"] == "chat_answer"
    assert result["reply_contract"]["source_constraints"]["disallow_news"] is True
    assert result["tasks"] == []
    assert result["chat_responded"] is True


def test_generic_company_compare_does_not_force_grounded_research():
    from backend.graph.nodes.conversation_router import (
        ContextBinding,
        ConversationDecision,
        normalize_context_decision,
    )

    normalized = normalize_context_decision(
        ConversationDecision(
            execution_route="research",
            context_binding=ContextBinding(source="none"),
            relation="compare",
            domain_intent="analysis",
            confidence=0.8,
            needs_tools=True,
        ),
        {"query": "Compare AAPL and MSFT quickly; no report format.", "ui_context": {}},
        tickers=["AAPL", "MSFT"],
        selection_ids=[],
    )

    assert normalized.execution_route == "direct_answer"
    assert normalized.needs_tools is False
    assert normalized.context_binding.subject_hint == "AAPL, MSFT"


def test_corrected_quote_request_still_uses_grounded_research():
    from backend.graph.nodes.conversation_router import (
        ContextBinding,
        ConversationDecision,
        normalize_context_decision,
    )

    normalized = normalize_context_decision(
        ConversationDecision(
            execution_route="direct_answer",
            context_binding=ContextBinding(source="none", subject_hint="NFLX"),
            relation="correct",
            domain_intent="quote",
            confidence=0.9,
            needs_tools=False,
        ),
        {"query": "Wrong ticker: use NFLX, not NVDA. Current price?", "ui_context": {}},
        tickers=["NFLX", "NVDA"],
        selection_ids=[],
    )

    assert normalized.execution_route == "research"
    assert normalized.needs_tools is True
    assert normalized.context_binding.subject_hint == "NFLX"


def test_explicit_subject_fallback_stays_chat_without_grounding_request():
    from backend.graph.nodes.conversation_router import _fallback_decision

    decision = _fallback_decision(
        {"query": "Do not generate a report; just summarize the three risks for AAPL."},
        tickers=["AAPL"],
        selection_ids=[],
    )

    assert decision is not None
    assert decision.execution_route == "direct_answer"
    assert decision.needs_tools is False


def test_explicit_subject_fallback_uses_research_for_quote_request():
    from backend.graph.nodes.conversation_router import _fallback_decision

    decision = _fallback_decision(
        {"query": "Wrong ticker: use NFLX, not NVDA. Current price?"},
        tickers=["NFLX", "NVDA"],
        selection_ids=[],
    )

    assert decision is not None
    assert decision.execution_route == "research"
    assert decision.needs_tools is True


def test_explicit_subject_fallback_uses_research_for_compound_grounded_analysis():
    from backend.graph.nodes.conversation_router import _fallback_decision

    decision = _fallback_decision(
        {"query": "请深度分析 INTC 最新财报、Arrow Lake 进展、NVIDIA/AMD/TSMC 竞争、分析师评级和目标价。"},
        tickers=["INTC", "NVDA", "AMD", "TSMC"],
        selection_ids=[],
    )

    assert decision is not None
    assert decision.execution_route == "research"
    assert decision.needs_tools is True


def test_no_news_constraint_keeps_qa_chat_lane_out_of_news_tools():
    from backend.graph.nodes.planner_stub import planner_stub
    from backend.graph.nodes.policy_gate import policy_gate

    state = {
        "query": "Why has NVDA dropped recently? No news or links, just explain the mechanism.",
        "output_mode": "chat",
        "reply_contract": {
            "lane": "chat_answer",
            "answer_style": "natural_chat",
            "source_constraints": {"disallow_news": True, "requires_sources": False},
            "citation_policy": "none",
        },
        "subject": {"subject_type": "company", "tickers": ["NVDA"]},
        "operation": {"name": "qa", "confidence": 0.8, "params": {}},
        "tasks": [
            {
                "id": "task_1",
                "subject_type": "company",
                "subject_label": "NVDA",
                "tickers": ["NVDA"],
                "operation": {"name": "qa", "confidence": 0.8, "params": {}},
                "status": "ready",
            }
        ],
    }

    state = {**state, **policy_gate(state)}
    tools = set((state.get("policy") or {}).get("allowed_tools") or [])
    assert "get_company_news" not in tools
    assert "get_authoritative_media_news" not in tools

    plan = planner_stub(state)["plan_ir"]
    step_names = [step.get("name") for step in plan.get("steps") or []]
    assert "get_company_news" not in step_names
    assert "get_authoritative_media_news" not in step_names


def test_no_sources_constraint_overrides_source_word():
    from backend.graph.request_task_contract import build_reply_contract

    contract = build_reply_contract(
        query="Direct answer only, no sources: what makes bank stocks sensitive to rates?",
        output_mode="chat",
        tasks=[],
    )

    assert contract["lane"] == "chat_answer"
    assert contract["citation_policy"] == "none"
    assert contract["source_constraints"]["disallow_news"] is True
    assert contract["source_constraints"]["requires_sources"] is False


def test_historical_report_does_not_become_continuation_target():
    from backend.graph.nodes.conversation_router import ContextBinding, ConversationDecision
    from backend.graph.request_task_contract import build_reply_contract

    contract = build_reply_contract(
        query="Continue point three.",
        output_mode="chat",
        tasks=[],
        conversation_decision=ConversationDecision(
            execution_route="direct_answer",
            context_binding=ContextBinding(source="last_report", subject_hint="AAPL old report"),
            relation="follow_up",
            domain_intent="report_discussion",
        ),
        memory_context={
            "historical_focus_memory": {
                "last_report": {
                    "report_id": "old-rpt",
                    "ticker": "AAPL",
                    "title": "AAPL old report",
                }
            }
        },
    )

    assert contract["continuation_target"] == {}


def test_current_report_populates_continuation_target():
    from backend.graph.nodes.conversation_router import ContextBinding, ConversationDecision
    from backend.graph.request_task_contract import build_reply_contract

    contract = build_reply_contract(
        query="Continue point three.",
        output_mode="chat",
        tasks=[],
        conversation_decision=ConversationDecision(
            execution_route="direct_answer",
            context_binding=ContextBinding(source="last_report", subject_hint="AAPL report"),
            relation="follow_up",
            domain_intent="report_discussion",
        ),
        memory_context={
            "current_report": {
                "report_id": "current-rpt",
                "ticker": "AAPL",
                "title": "AAPL report",
            }
        },
    )

    assert contract["continuation_target"] == {
        "type": "last_report",
        "report_id": "current-rpt",
        "ticker": "AAPL",
        "title": "AAPL report",
    }


def test_compound_alert_news_preserves_research_after_alert(monkeypatch):
    import importlib

    from backend.graph.nodes.conversation_router import ContextBinding, ConversationDecision

    understand_mod = importlib.import_module("backend.graph.nodes.understand_request")

    async def fake_route_conversation(_state, *, tickers, selection_ids):
        return ConversationDecision(
            execution_route="alert",
            context_binding=ContextBinding(source="none", subject_hint=", ".join(tickers)),
            relation="new_topic",
            domain_intent="alert",
            confidence=0.9,
            needs_tools=False,
        )

    monkeypatch.setattr(understand_mod, "route_conversation", fake_route_conversation)

    result = _run(
        understand_mod.understand_request(
            {
                "query": "Set an alert if TSLA breaks 180, and also give recent news links.",
                "output_mode": "chat",
                "ui_context": {"user_email": "eval@example.com"},
                "trace": {},
            }
        )
    )

    operations = [(task.get("operation") or {}).get("name") for task in result.get("tasks") or []]
    assert operations[0] == "fetch"
    assert "alert_set" in operations
    assert result["understanding"]["route"] == "alert"
    assert result["pending_research_after_alert"] is True
    assert result["reply_contract"]["lane"] == "source_grounded_answer"


def test_semiconductor_sector_headlines_project_theme_fetch(monkeypatch):
    import importlib

    from backend.graph.nodes.conversation_router import ContextBinding, ConversationDecision

    understand_mod = importlib.import_module("backend.graph.nodes.understand_request")

    async def fake_route_conversation(_state, *, tickers, selection_ids):
        return ConversationDecision(
            execution_route="research",
            context_binding=ContextBinding(source="none"),
            relation="new_topic",
            domain_intent="news",
            confidence=0.9,
            needs_tools=True,
            task_hints=(
                {
                    "subject_type": "unknown",
                    "subject_label": "semiconductor sector",
                    "tickers": [],
                    "operation": "fetch",
                    "params": {"topic": "news"},
                },
            ),
        )

    monkeypatch.setattr(understand_mod, "route_conversation", fake_route_conversation)

    result = _run(
        understand_mod.understand_request(
            {
                "query": "Give links for today's semiconductor sector headlines.",
                "output_mode": "chat",
                "ui_context": {},
                "trace": {},
            }
        )
    )

    assert result["reply_contract"]["lane"] == "source_grounded_answer"
    assert any(
        task.get("subject_type") == "theme"
        and (task.get("operation") or {}).get("name") in {"fetch", "news_impact"}
        for task in result.get("tasks") or []
    )


def test_single_theme_fetch_task_plans_search_steps():
    from backend.graph.nodes.planner_stub import planner_stub
    from backend.graph.nodes.policy_gate import policy_gate

    state = {
        "query": "Give links for today's semiconductor sector headlines.",
        "output_mode": "chat",
        "reply_contract": {
            "lane": "source_grounded_answer",
            "source_constraints": {"requires_links": True, "requires_sources": True},
            "citation_policy": "must_cite_or_disclose_unavailable",
        },
        "subject": {"subject_type": "theme", "subject_label": "semiconductor sector", "tickers": []},
        "operation": {"name": "fetch", "confidence": 0.9, "params": {"topic": "news"}},
        "tasks": [
            {
                "id": "task_1",
                "subject_type": "theme",
                "subject_label": "semiconductor sector",
                "tickers": [],
                "operation": {"name": "fetch", "confidence": 0.9, "params": {"topic": "news"}},
                "status": "ready",
            }
        ],
    }

    state = {**state, **policy_gate(state)}
    plan = planner_stub(state)["plan_ir"]
    step_names = [step.get("name") for step in plan.get("steps") or []]

    assert "search" in step_names
    assert "get_authoritative_media_news" in step_names


def test_price_turn_contract_allows_quote_tool():
    from backend.graph.nodes.planner_stub import planner_stub
    from backend.graph.nodes.policy_gate import policy_gate

    state = {
        "query": "What is AAPL trading at now?",
        "output_mode": "chat",
        "reply_contract": {
            "lane": "source_grounded_answer",
            "answer_style": "grounded_concise",
            "source_constraints": {"requires_realtime": True, "requires_sources": True},
            "citation_policy": "must_cite_or_disclose_unavailable",
        },
        "subject": {"subject_type": "company", "tickers": ["AAPL"]},
        "operation": {"name": "price", "confidence": 0.9, "params": {}},
        "tasks": [
            {
                "id": "task_1",
                "subject_type": "company",
                "subject_label": "AAPL",
                "tickers": ["AAPL"],
                "operation": {"name": "price", "confidence": 0.9, "params": {}},
                "status": "ready",
            }
        ],
    }

    state = {**state, **policy_gate(state)}
    assert "get_stock_price" in set((state.get("policy") or {}).get("allowed_tools") or [])

    plan = planner_stub(state)["plan_ir"]
    assert ("get_stock_price", {"ticker": "AAPL"}) in [
        (step.get("name"), step.get("inputs")) for step in plan.get("steps") or []
    ]


def test_single_url_task_plans_fetch_url_content():
    from backend.graph.nodes.planner_stub import planner_stub
    from backend.graph.nodes.policy_gate import policy_gate

    state = {
        "query": "Read https://example.com/blocked-aapl.",
        "output_mode": "chat",
        "reply_contract": {
            "lane": "source_grounded_answer",
            "answer_style": "grounded_concise",
            "source_constraints": {"requires_url_fetch": True, "requires_sources": True},
            "citation_policy": "must_cite_or_disclose_unavailable",
        },
        "subject": {"subject_type": "research_doc", "tickers": [], "selection_payload": []},
        "operation": {
            "name": "fetch",
            "confidence": 0.8,
            "params": {"url": "https://example.com/blocked-aapl"},
        },
        "tasks": [
            {
                "id": "task_1",
                "subject_type": "research_doc",
                "subject_label": "provided URL",
                "tickers": [],
                "operation": {
                    "name": "fetch",
                    "confidence": 0.8,
                    "params": {"url": "https://example.com/blocked-aapl"},
                },
                "status": "ready",
            }
        ],
    }

    state = {**state, **policy_gate(state)}
    plan = planner_stub(state)["plan_ir"]
    steps = plan.get("steps") or []
    assert ("fetch_url_content", {"url": "https://example.com/blocked-aapl", "max_length": 6000}) in [
        (step.get("name"), step.get("inputs")) for step in steps
    ]


def test_finance_concept_clarify_normalizes_to_direct_answer():
    from backend.graph.nodes.conversation_router import (
        ContextBinding,
        ConversationDecision,
        _STRUCTURAL_DEIXIS_RE,
        normalize_context_decision,
    )

    assert _STRUCTURAL_DEIXIS_RE.search("might") is None
    assert _STRUCTURAL_DEIXIS_RE.search("Keep it conversational.") is None
    assert _STRUCTURAL_DEIXIS_RE.search("What is its biggest risk?") is not None

    decision = ConversationDecision(
        execution_route="clarify",
        context_binding=ContextBinding(source="none"),
        relation="new_topic",
        domain_intent="finance_concept",
        confidence=0.45,
        needs_tools=False,
    )

    normalized = normalize_context_decision(
        decision,
        {"query": "Why might US stocks rally after a weak jobs report?", "ui_context": {}},
        tickers=[],
        selection_ids=[],
    )

    assert normalized.execution_route == "direct_answer"
    assert normalized.domain_intent == "finance_concept"
    assert normalized.needs_tools is False


def test_ordinary_research_mechanism_decision_normalizes_to_chat():
    from backend.graph.nodes.conversation_router import (
        ContextBinding,
        ConversationDecision,
        normalize_context_decision,
    )

    decision = ConversationDecision(
        execution_route="research",
        context_binding=ContextBinding(source="none", subject_hint="CL=F"),
        relation="new_topic",
        domain_intent="finance_concept",
        confidence=0.55,
        needs_tools=True,
        task_hints=(
            {
                "subject_type": "macro",
                "subject_label": "oil prices and airlines",
                "operation": "analyze_impact",
                "params": {},
            },
        ),
    )

    normalized = normalize_context_decision(
        decision,
        {"query": "Why can oil prices affect inflation expectations and airlines?", "ui_context": {}},
        tickers=["CL=F"],
        selection_ids=[],
    )

    assert normalized.execution_route == "direct_answer"
    assert normalized.needs_tools is False
    assert normalized.task_hints == ()


def test_synthetic_macro_proxy_hint_does_not_force_mechanism_research():
    from backend.graph.nodes.conversation_router import (
        ContextBinding,
        ConversationDecision,
        normalize_context_decision,
    )

    decision = ConversationDecision(
        execution_route="research",
        context_binding=ContextBinding(source="none", subject_hint="oil prices"),
        relation="new_topic",
        domain_intent="finance_concept",
        confidence=0.55,
        needs_tools=True,
        task_hints=(
            {
                "subject_type": "macro",
                "subject_label": "oil prices",
                "tickers": ["CL=F"],
                "operation": "analyze_impact",
                "params": {},
            },
        ),
    )

    normalized = normalize_context_decision(
        decision,
        {"query": "Why can oil prices affect inflation expectations and airlines?", "ui_context": {}},
        tickers=[],
        selection_ids=[],
    )

    assert normalized.execution_route == "direct_answer"
    assert normalized.needs_tools is False
    assert normalized.task_hints == ()


def test_current_data_macro_proxy_hint_still_requires_research():
    from backend.graph.nodes.conversation_router import _task_hints_require_execution

    task_hints = (
        {
            "subject_type": "macro",
            "subject_label": "oil prices",
            "tickers": ["CL=F"],
            "operation": "analyze_impact",
            "params": {},
        },
    )

    assert _task_hints_require_execution(
        task_hints,
        "How are current oil prices affecting inflation expectations and airlines?",
    )


def test_price_word_in_mechanism_question_does_not_force_quote_tasks(monkeypatch):
    import importlib

    from backend.graph.nodes.conversation_router import ContextBinding, ConversationDecision

    understand_mod = importlib.import_module("backend.graph.nodes.understand_request")

    async def fake_route_conversation(_state, *, tickers, selection_ids):
        return ConversationDecision(
            execution_route="direct_answer",
            context_binding=ContextBinding(source="none", subject_hint=", ".join(tickers)),
            relation="new_topic",
            domain_intent="finance_concept",
            confidence=0.8,
            needs_tools=False,
        )

    async def fake_generate_contextual_reply(_state, _decision):
        return "Oil can affect inflation expectations and airline margins through energy costs."

    monkeypatch.setattr(understand_mod, "route_conversation", fake_route_conversation)
    monkeypatch.setattr(understand_mod, "generate_contextual_reply", fake_generate_contextual_reply)

    result = _run(
        understand_mod.understand_request(
            {
                "query": "Why can oil prices affect inflation expectations and airlines?",
                "output_mode": "chat",
                "ui_context": {},
                "trace": {},
            }
        )
    )

    assert (result.get("understanding") or {}).get("route") == "direct"
    assert result.get("tasks") == []
    assert (result.get("reply_contract") or {}).get("lane") == "chat_answer"


def test_deictic_followup_prefers_same_session_last_turn_over_recent_focus():
    from backend.graph.nodes.conversation_router import (
        ContextBinding,
        ConversationDecision,
        normalize_context_decision,
    )

    decision = ConversationDecision(
        execution_route="direct_answer",
        context_binding=ContextBinding(
            source="recent_focus",
            confidence=0.9,
            subject_hint="AAPL",
            reason="user memory recent focus",
        ),
        relation="follow_up",
        domain_intent="analysis",
        confidence=0.9,
        needs_tools=False,
    )

    normalized = normalize_context_decision(
        decision,
        {
            "query": "What is its biggest risk?",
            "ui_context": {
                "session_history": [
                    {"role": "user", "content": "MSFT latest news with links.", "tickers": "MSFT"},
                    {"role": "assistant", "content": "MSFT news summary."},
                ]
            },
        },
        tickers=[],
        selection_ids=[],
    )

    assert normalized.context_binding.source == "last_turn"
    assert normalized.context_binding.subject_hint == "MSFT"
