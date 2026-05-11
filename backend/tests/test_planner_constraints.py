# -*- coding: utf-8 -*-
from backend.graph.nodes.planner_stub import planner_stub


def test_planner_includes_selection_summary_step_first_when_selection_present():
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
        "policy": {"budget": {"max_rounds": 3, "max_tools": 4}, "allowed_tools": ["search"]},
    }
    result = planner_stub(state)
    plan = result.get("plan_ir") or {}
    steps = plan.get("steps") or []
    assert steps, "planner should add at least selection summary step"
    assert steps[0].get("name") == "summarize_selection"
    assert steps[0].get("kind") == "llm"


def test_planner_does_not_add_report_fill_steps_when_not_investment_report_mode():
    state = {
        "query": "分析影响",
        "output_mode": "brief",
        "operation": {"name": "analyze_impact", "confidence": 0.7, "params": {}},
        "subject": {
            "subject_type": "company",
            "tickers": ["AAPL"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "policy": {"budget": {"max_rounds": 3, "max_tools": 4}, "allowed_tools": ["get_company_info"]},
    }
    plan = (planner_stub(state).get("plan_ir") or {})
    names = [s.get("name") for s in (plan.get("steps") or [])]
    assert not any("report" in (n or "") for n in names)


def test_planner_no_selection_no_summary_step():
    state = {
        "query": "分析影响",
        "output_mode": "brief",
        "operation": {"name": "qa", "confidence": 0.5, "params": {}},
        "subject": {
            "subject_type": "company",
            "tickers": ["AAPL"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "policy": {"budget": {"max_rounds": 3, "max_tools": 4}, "allowed_tools": []},
    }
    plan = (planner_stub(state).get("plan_ir") or {})
    names = [s.get("name") for s in (plan.get("steps") or [])]
    assert "summarize_selection" not in names


def test_planner_plain_chat_qa_does_not_auto_expand_live_company_tools():
    state = {
        "query": "那它的风险主要在哪？",
        "output_mode": "chat",
        "operation": {"name": "qa", "confidence": 0.7, "params": {}},
        "subject": {
            "subject_type": "company",
            "tickers": ["AAPL"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "tasks": [
            {
                "id": "task_1",
                "subject_type": "company",
                "tickers": ["AAPL"],
                "operation": {"name": "qa", "confidence": 0.7, "params": {}},
                "status": "ready",
            }
        ],
        "policy": {
            "budget": {"max_rounds": 3, "max_tools": 4},
            "allowed_tools": ["get_stock_price", "get_company_news", "get_company_info"],
        },
    }
    plan = (planner_stub(state).get("plan_ir") or {})
    names = [s.get("name") for s in (plan.get("steps") or [])]
    assert "get_stock_price" not in names
    assert "get_company_news" not in names
    assert "get_company_info" not in names


def test_planner_lightweight_representative_qa_does_not_fetch_performance_compare():
    state = {
        "query": "先别长篇，半导体 ETF 能不能看？如果不知道就按 NVDA、AMD、TSM 这几个代表说。",
        "output_mode": "chat",
        "operation": {"name": "qa", "confidence": 0.7, "params": {}},
        "subject": {
            "subject_type": "company",
            "tickers": ["NVDA", "AMD", "TSM"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "tasks": [
            {
                "id": "task_1",
                "subject_type": "company",
                "tickers": ["NVDA", "AMD", "TSM"],
                "operation": {"name": "qa", "confidence": 0.7, "params": {}},
                "status": "ready",
            }
        ],
        "policy": {
            "budget": {"max_rounds": 3, "max_tools": 4},
            "allowed_tools": ["get_performance_comparison", "get_stock_price", "get_company_news"],
        },
    }
    plan = (planner_stub(state).get("plan_ir") or {})
    names = [s.get("name") for s in (plan.get("steps") or [])]
    assert "get_performance_comparison" not in names
    assert "get_stock_price" not in names
    assert "get_company_news" not in names


def test_planner_multiticker_quote_uses_parallel_price_steps_not_performance_compare():
    state = {
        "query": "苹果、微软、谷歌现在分别多少？",
        "output_mode": "chat",
        "operation": {"name": "price", "confidence": 0.9, "params": {}},
        "subject": {
            "subject_type": "company",
            "tickers": ["AAPL", "GOOGL", "MSFT"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "tasks": [
            {
                "id": "task_1",
                "subject_type": "company",
                "tickers": ["AAPL"],
                "operation": {"name": "price", "confidence": 0.9, "params": {}},
                "status": "ready",
            },
            {
                "id": "task_2",
                "subject_type": "company",
                "tickers": ["GOOGL"],
                "operation": {"name": "price", "confidence": 0.9, "params": {}},
                "status": "ready",
            },
            {
                "id": "task_3",
                "subject_type": "company",
                "tickers": ["MSFT"],
                "operation": {"name": "price", "confidence": 0.9, "params": {}},
                "status": "ready",
            },
        ],
        "policy": {
            "budget": {"max_rounds": 3, "max_tools": 4},
            "allowed_tools": ["get_performance_comparison", "get_stock_price", "get_company_news"],
        },
    }
    plan = (planner_stub(state).get("plan_ir") or {})
    steps = plan.get("steps") or []
    names = [s.get("name") for s in steps]
    assert "get_performance_comparison" not in names
    assert names.count("get_stock_price") == 3
    assert {(s.get("inputs") or {}).get("ticker") for s in steps if s.get("name") == "get_stock_price"} == {
        "AAPL",
        "GOOGL",
        "MSFT",
    }
    assert {s.get("parallel_group") for s in steps if s.get("name") == "get_stock_price"} == {"price_quotes"}


def test_planner_chat_compare_with_current_subtasks_skips_historical_performance_compare():
    state = {
        "query": "先别做长报告，30秒告诉我 GOOGL 和 MSFT 今天谁更强，新闻、涨跌幅、风险点各一句。",
        "output_mode": "brief",
        "operation": {"name": "compare", "confidence": 0.86, "params": {}},
        "subject": {
            "subject_type": "company",
            "tickers": ["GOOGL", "MSFT"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "tasks": [
            {
                "id": "task_1",
                "subject_type": "company",
                "tickers": ["GOOGL", "MSFT"],
                "operation": {"name": "compare", "confidence": 0.86, "params": {}},
                "status": "ready",
            },
            {
                "id": "task_2",
                "subject_type": "company",
                "tickers": ["GOOGL"],
                "operation": {"name": "price", "confidence": 0.82, "params": {}},
                "status": "ready",
            },
            {
                "id": "task_3",
                "subject_type": "company",
                "tickers": ["GOOGL"],
                "operation": {"name": "fetch", "confidence": 0.78, "params": {"topic": "news"}},
                "status": "ready",
            },
            {
                "id": "task_4",
                "subject_type": "company",
                "tickers": ["MSFT"],
                "operation": {"name": "price", "confidence": 0.82, "params": {}},
                "status": "ready",
            },
            {
                "id": "task_5",
                "subject_type": "company",
                "tickers": ["MSFT"],
                "operation": {"name": "fetch", "confidence": 0.78, "params": {"topic": "news"}},
                "status": "ready",
            },
        ],
        "policy": {
            "budget": {"max_rounds": 3, "max_tools": 8},
            "allowed_tools": ["get_performance_comparison", "get_stock_price", "get_company_news"],
        },
    }
    plan = (planner_stub(state).get("plan_ir") or {})
    steps = plan.get("steps") or []
    names = [s.get("name") for s in steps]
    assert "get_performance_comparison" not in names
    assert names.count("get_stock_price") == 2
    assert names.count("get_company_news") == 2


def test_understand_lightweight_representative_query_stays_chat_without_current_data_request():
    import asyncio

    from backend.graph.nodes.understand_request import understand_request

    result = asyncio.run(
        understand_request(
            {
                "query": "先别长篇，半导体 ETF 能不能看？如果不知道就按 NVDA、AMD、TSM 这几个代表说。",
                "output_mode": "chat",
                "ui_context": {},
                "trace": {},
            }
        )
    )
    tasks = result.get("tasks") or []
    assert tasks == []
    assert (result.get("understanding") or {}).get("route") == "direct"
    assert (result.get("reply_contract") or {}).get("lane") == "chat_answer"


def test_planner_stub_report_analysis_depth_excludes_deep_search(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_REPORT_MAX_AGENTS", "4")
    monkeypatch.setenv("LANGGRAPH_REPORT_MIN_AGENTS", "2")

    state = {
        "query": "Deep research for AAPL and generate investment report",
        "output_mode": "investment_report",
        "operation": {"name": "generate_report", "confidence": 0.9, "params": {}},
        "subject": {
            "subject_type": "company",
            "tickers": ["AAPL"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "ui_context": {"analysis_depth": "report"},
        "policy": {
            "budget": {"max_rounds": 6, "max_tools": 8},
            "allowed_tools": ["search", "get_stock_price"],
            "allowed_agents": [
                "price_agent",
                "news_agent",
                "fundamental_agent",
                "technical_agent",
                "macro_agent",
                "deep_search_agent",
            ],
        },
    }

    plan = (planner_stub(state).get("plan_ir") or {})
    names = [s.get("name") for s in (plan.get("steps") or []) if s.get("kind") == "agent"]
    assert "deep_search_agent" not in names


def test_planner_stub_deep_research_forces_deep_search_without_keywords(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_REPORT_MAX_AGENTS", "1")
    monkeypatch.setenv("LANGGRAPH_REPORT_MIN_AGENTS", "1")

    state = {
        "query": "Generate investment report for AAPL",
        "output_mode": "investment_report",
        "operation": {"name": "generate_report", "confidence": 0.9, "params": {}},
        "subject": {
            "subject_type": "company",
            "tickers": ["AAPL"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "ui_context": {"analysis_depth": "deep_research"},
        "policy": {
            "budget": {"max_rounds": 6, "max_tools": 8},
            "allowed_tools": ["search", "get_stock_price"],
            "allowed_agents": ["price_agent", "deep_search_agent"],
        },
    }

    plan = (planner_stub(state).get("plan_ir") or {})
    names = [s.get("name") for s in (plan.get("steps") or []) if s.get("kind") == "agent"]
    assert "deep_search_agent" in names


def test_planner_stub_force_all_agents_skips_report_caps(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_REPORT_MAX_AGENTS", "1")
    monkeypatch.setenv("LANGGRAPH_REPORT_MIN_AGENTS", "1")

    full_agents = [
        "price_agent",
        "news_agent",
        "fundamental_agent",
        "technical_agent",
        "macro_agent",
        "risk_agent",
        "deep_search_agent",
    ]
    state = {
        "query": "Generate investment report for AAPL",
        "output_mode": "investment_report",
        "operation": {"name": "generate_report", "confidence": 0.9, "params": {}},
        "subject": {
            "subject_type": "company",
            "tickers": ["AAPL"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "policy": {
            "budget": {"max_rounds": 10, "max_tools": 12},
            "allowed_tools": ["search", "get_stock_price"],
            "allowed_agents": full_agents,
            "force_all_agents": True,
            "agent_selection": {
                "selected": full_agents,
                "required": full_agents,
                "force_all_agents": True,
            },
        },
    }

    plan = (planner_stub(state).get("plan_ir") or {})
    names = [s.get("name") for s in (plan.get("steps") or []) if s.get("kind") == "agent"]
    assert names == full_agents
