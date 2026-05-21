# -*- coding: utf-8 -*-
import asyncio


def _run(coro):
    return asyncio.run(coro)


def _task_ops(result: dict) -> list[tuple[str, tuple[str, ...], str]]:
    rows = []
    for task in result.get("tasks") or []:
        rows.append(
            (
                task.get("subject_type"),
                tuple(task.get("tickers") or []),
                (task.get("operation") or {}).get("name"),
            )
        )
    return rows


def test_pure_greeting_routes_direct_without_research_pipeline():
    from backend.graph import GraphRunner

    result = _run(GraphRunner.create().ainvoke(thread_id="u-direct", query="你好", ui_context={}))

    # 2026-05-03: chat_respond is now wired into the main flow and intercepts
    # pure greetings via Tier-1 rule whitelist before understand_request runs,
    # so the run terminates at chat_respond. understanding/tasks are never
    # populated (left as the reset_turn_state default of None).
    assert result.get("chat_responded") is True
    assert not result.get("tasks")
    nodes = [s.get("node") for s in (result.get("trace") or {}).get("spans") or []]
    assert nodes == [
        "build_initial_state",
        "reset_turn_state",
        "prepare_context",
        "chat_respond",
    ]


def test_chinese_company_alias_question_stays_natural_chat_without_grounding_request():
    from backend.graph import GraphRunner

    result = _run(GraphRunner.create().ainvoke(thread_id="u-google", query="谷歌AI业务进展如何", ui_context={}))

    assert (result.get("understanding") or {}).get("route") == "direct"
    assert (result.get("reply_contract") or {}).get("lane") == "chat_answer"
    assert result.get("tasks") == []


def test_macro_query_without_ticker_is_executable():
    from backend.graph import GraphRunner

    result = _run(
        GraphRunner.create().ainvoke(
            thread_id="u-macro",
            query="美联储利率路径对大型科技股估值有什么影响",
            ui_context={},
        )
    )

    assert (result.get("subject") or {}).get("subject_type") == "macro"
    assert (result.get("operation") or {}).get("name") == "analyze_impact"
    assert (result.get("clarify") or {}).get("needed") is False


def test_macro_tech_query_does_not_add_duplicate_theme_task():
    from backend.graph import GraphRunner

    result = _run(
        GraphRunner.create().ainvoke(
            thread_id="u-macro-tech-theme",
            query="CPI 对科技股有什么影响",
            ui_context={},
        )
    )

    tasks = result.get("tasks") or []
    assert [task.get("subject_type") for task in tasks] == ["macro"]
    assert tasks[0].get("subject_label") == "CPI / 科技股"


def test_compare_risk_query_does_not_expand_to_per_ticker_impact_tasks():
    from backend.graph import GraphRunner

    result = _run(
        GraphRunner.create().ainvoke(
            thread_id="u-compare-risk-only",
            query="对比 AAPL 和 MSFT 最新表现，哪个风险更高",
            ui_context={},
        )
    )

    ops = _task_ops(result)
    assert ("company", ("AAPL", "MSFT"), "compare") in ops
    assert not any(row[2] == "analyze_impact" for row in ops)


def test_mixed_social_company_news_price_and_portfolio_blocked_locally():
    from backend.graph import GraphRunner

    query = (
        "你好，今天天气不错，帮我看看谷歌昨天涨了多少，谷歌有什么新闻，"
        "然后微软呢？微软的新闻和涨幅如何？最近有没有发生什么大事影响我的几只股票？"
        "我的调仓要变动吗？"
    )
    result = _run(GraphRunner.create().ainvoke(thread_id="u-mixed", query=query, ui_context={}))

    understanding = result.get("understanding") or {}
    ops = _task_ops(result)
    assert understanding.get("route") == "research"
    assert ("company", ("GOOGL",), "price") in ops
    assert ("company", ("GOOGL",), "fetch") in ops
    assert ("company", ("MSFT",), "price") in ops
    assert ("company", ("MSFT",), "fetch") in ops
    blocked = result.get("blocked_tasks") or []
    assert any(item.get("reason") == "missing_portfolio_holdings" for item in blocked)
    assert (result.get("clarify") or {}).get("needed") is False


def test_explicit_holdings_make_portfolio_task_ready():
    from backend.graph import GraphRunner

    query = "我持有 AAPL 和 MSFT，今天美联储消息会影响我的仓位吗，要不要调仓？"
    result = _run(GraphRunner.create().ainvoke(thread_id="u-holdings", query=query, ui_context={}))

    ops = _task_ops(result)
    assert ("portfolio", ("AAPL", "MSFT"), "rebalance_check") in ops
    assert result.get("blocked_tasks") == []


def test_user_fallback_prevents_global_clarify_for_missing_portfolio():
    from backend.graph import GraphRunner

    query = "今天有什么大新闻会影响我的持仓吗？如果不知道我的持仓就按等权大型科技股估算。"
    result = _run(GraphRunner.create().ainvoke(thread_id="u-fallback", query=query, ui_context={}))

    understanding = result.get("understanding") or {}
    assert understanding.get("route") == "research"
    assert any(task.get("subject_type") == "portfolio" for task in result.get("tasks") or [])
    assert result.get("blocked_tasks") == []
    assert understanding.get("fallback_assumptions")


def test_compare_query_keeps_price_news_and_risk_subtasks():
    from backend.graph import GraphRunner

    query = "先别做长报告，30秒告诉我谷歌和微软今天谁更强，新闻、涨跌幅、风险点各一句。"
    result = _run(GraphRunner.create().ainvoke(thread_id="u-compare-subtasks", query=query, ui_context={}))

    ops = _task_ops(result)
    assert ("company", ("GOOGL", "MSFT"), "compare") in ops
    assert ("company", ("GOOGL",), "price") in ops
    assert ("company", ("GOOGL",), "fetch") in ops
    assert ("company", ("MSFT",), "price") in ops
    assert ("company", ("MSFT",), "fetch") in ops


def test_multiticker_fail_open_chat_defaults_to_quotes_not_history_compare():
    from backend.graph.nodes.understand_request import understand_request

    result = _run(
        understand_request(
            {
                "query": "AAPL MSFT GOOGL now?",
                "output_mode": "chat",
                "ui_context": {},
                "trace": {},
            }
        )
    )

    ops = _task_ops(result)
    assert ("company", ("AAPL",), "price") in ops
    assert ("company", ("MSFT",), "price") in ops
    assert ("company", ("GOOGL",), "price") in ops
    assert not any(row[2] == "compare" for row in ops)


def test_single_company_deep_report_keeps_competitors_as_context_not_subjects():
    from backend.graph.nodes.understand_request import understand_request

    query = (
        "请给我一份 INTC 英特尔深度投资报告，覆盖最新财报、Arrow Lake、"
        "NVIDIA/AMD/TSMC 竞争、分析师评级、估值和未来6-12个月风险机会。"
        "不要问我要不要启动研究，直接给报告。"
    )
    result = _run(
        understand_request(
            {
                "query": query,
                "output_mode": "investment_report",
                "ui_context": {},
                "trace": {},
            }
        )
    )

    assert (result.get("subject") or {}).get("tickers") == ["INTC"]
    assert (result.get("operation") or {}).get("name") != "compare"
    tasks = result.get("tasks") or []
    assert tasks
    assert all(task.get("tickers") == ["INTC"] for task in tasks)
    assert not any((task.get("operation") or {}).get("name") == "compare" for task in tasks)
    peer_sets = [
        set(((task.get("operation") or {}).get("params") or {}).get("peer_tickers") or [])
        for task in tasks
    ]
    assert any({"AMD", "TSM", "NVDA"}.issubset(peers) for peers in peer_sets)


def test_explicit_compare_deep_report_still_uses_compare_subject():
    from backend.graph.nodes.understand_request import understand_request

    result = _run(
        understand_request(
            {
                "query": "请比较 INTC、AMD、NVDA、TSMC 谁未来一年更值得买，并输出深度报告。",
                "output_mode": "investment_report",
                "ui_context": {},
                "trace": {},
            }
        )
    )

    assert (result.get("subject") or {}).get("is_comparison") is True
    assert (result.get("operation") or {}).get("name") == "compare"
    assert any((task.get("operation") or {}).get("name") == "compare" for task in result.get("tasks") or [])


def test_explicit_url_is_preserved_as_tool_task_without_prefetch():
    from backend.graph.nodes.understand_request import understand_request

    result = _run(
        understand_request(
            {
                "query": "AAPL price and read https://example.com/msft-rates for MSFT",
                "output_mode": "chat",
                "ui_context": {},
                "trace": {},
            }
        )
    )

    tasks = result.get("tasks") or []
    url_tasks = [
        task
        for task in tasks
        if isinstance((task.get("operation") or {}).get("params"), dict)
        and (task.get("operation") or {}).get("params", {}).get("url") == "https://example.com/msft-rates"
    ]
    assert url_tasks
    assert "MSFT" in [str(t).upper() for t in (url_tasks[0].get("tickers") or [])]
    assert not (result.get("artifacts") or {}).get("url_context")


def test_url_only_company_question_does_not_spawn_daily_brief():
    from backend.graph.nodes.understand_request import understand_request

    result = _run(
        understand_request(
            {
                "query": "Read https://example.com/msft-rates and tell me whether it matters for MSFT.",
                "output_mode": "chat",
                "ui_context": {},
                "trace": {},
            }
        )
    )

    tasks = result.get("tasks") or []
    assert any(
        (task.get("operation") or {}).get("params", {}).get("url") == "https://example.com/msft-rates"
        for task in tasks
    )
    assert not any(
        task.get("reason") == "conversation_router_intent"
        and (task.get("operation") or {}).get("name") == "daily_brief"
        for task in tasks
    )


def test_url_only_document_question_does_not_spawn_theme_search_from_text_substrings():
    from backend.graph.nodes.understand_request import understand_request

    result = _run(
        understand_request(
            {
                "query": "Read https://example.com/empty and disclose if no usable content is available.",
                "output_mode": "chat",
                "ui_context": {},
                "trace": {},
            }
        )
    )

    tasks = result.get("tasks") or []
    assert [
        ((task.get("operation") or {}).get("name"), task.get("reason"))
        for task in tasks
    ] == [("qa", "explicit_url_reference")]


def test_multi_ticker_report_keeps_compare_context_and_supporting_tasks():
    from backend.graph.nodes.understand_request import understand_request

    result = _run(
        understand_request(
            {
                "query": "分析 GOOGL 和 MSFT，生成报告。",
                "output_mode": "investment_report",
                "ui_context": {},
                "trace": {},
            }
        )
    )

    ops = _task_ops(result)
    assert ("company", ("GOOGL", "MSFT"), "compare") in ops
    assert ("company", ("GOOGL",), "price") in ops
    assert ("company", ("GOOGL",), "fetch") in ops
    assert ("company", ("MSFT",), "price") in ops
    assert ("company", ("MSFT",), "fetch") in ops
    assert (result.get("subject") or {}).get("tickers") == ["GOOGL", "MSFT"]
    assert (result.get("operation") or {}).get("name") == "compare"


def test_alert_below_price_routes_to_alert_extractor():
    from backend.graph import GraphRunner

    result = _run(GraphRunner.create().ainvoke(thread_id="u-alert-below", query="TSLA 跌破 200 提醒我", ui_context={}))

    understanding = result.get("understanding") or {}
    assert understanding.get("route") == "alert"
    assert (result.get("operation") or {}).get("name") == "alert_set"


def test_document_selection_and_company_comparison_create_two_contexts():
    from backend.graph import GraphRunner

    result = _run(
        GraphRunner.create().ainvoke(
            thread_id="u-doc-compare",
            query="这个PDF里的公司和谷歌相比怎么样？重点看收入增长和估值。",
            ui_context={"selection": {"type": "doc", "id": "d1", "title": "research.pdf"}},
        )
    )

    ops = _task_ops(result)
    assert any(row[0] == "research_doc" for row in ops)
    assert any(row[1] == ("GOOGL",) for row in ops)
    assert (result.get("subject") or {}).get("subject_type") == "research_doc"


def test_policy_gate_unions_tools_for_all_understanding_tasks():
    from backend.graph.nodes.policy_gate import policy_gate

    state = {
        "query": "谷歌昨天涨了多少，谷歌有什么新闻，然后微软呢？美联储降息没？",
        "output_mode": "brief",
        "subject": {"subject_type": "company", "tickers": ["GOOGL"]},
        "operation": {"name": "price", "confidence": 0.8, "params": {}},
        "tasks": [
            {
                "id": "task_1",
                "subject_type": "company",
                "tickers": ["GOOGL"],
                "operation": {"name": "price", "confidence": 0.8, "params": {}},
                "status": "ready",
            },
            {
                "id": "task_2",
                "subject_type": "company",
                "tickers": ["GOOGL"],
                "operation": {"name": "fetch", "confidence": 0.8, "params": {}},
                "status": "ready",
            },
            {
                "id": "task_3",
                "subject_type": "company",
                "tickers": ["MSFT"],
                "operation": {"name": "fetch", "confidence": 0.8, "params": {}},
                "status": "ready",
            },
            {
                "id": "task_4",
                "subject_type": "macro",
                "tickers": [],
                "operation": {"name": "fact_check", "confidence": 0.8, "params": {}},
                "status": "ready",
            },
        ],
    }

    policy = policy_gate(state)["policy"]
    tools = set(policy["allowed_tools"])

    assert "get_stock_price" in tools
    assert "get_company_news" in tools
    assert "get_official_macro_releases" in tools
    assert "get_authoritative_media_news" in tools
    assert policy["budget"]["max_tools"] >= 8


def test_planner_stub_builds_multitask_steps_from_understanding_tasks():
    from backend.graph.nodes.planner_stub import planner_stub
    from backend.graph.nodes.policy_gate import policy_gate

    state = {
        "query": "谷歌昨天涨了多少，谷歌有什么新闻，然后微软呢？微软新闻如何？美联储降息没？",
        "output_mode": "brief",
        "subject": {"subject_type": "company", "tickers": ["GOOGL"]},
        "operation": {"name": "price", "confidence": 0.8, "params": {}},
        "tasks": [
            {
                "id": "task_1",
                "subject_type": "company",
                "tickers": ["GOOGL"],
                "operation": {"name": "price", "confidence": 0.8, "params": {}},
                "status": "ready",
            },
            {
                "id": "task_2",
                "subject_type": "company",
                "tickers": ["GOOGL"],
                "operation": {"name": "fetch", "confidence": 0.8, "params": {}},
                "status": "ready",
            },
            {
                "id": "task_3",
                "subject_type": "company",
                "tickers": ["MSFT"],
                "operation": {"name": "price", "confidence": 0.8, "params": {}},
                "status": "ready",
            },
            {
                "id": "task_4",
                "subject_type": "company",
                "tickers": ["MSFT"],
                "operation": {"name": "fetch", "confidence": 0.8, "params": {}},
                "status": "ready",
            },
            {
                "id": "task_5",
                "subject_type": "macro",
                "tickers": [],
                "operation": {"name": "fact_check", "confidence": 0.8, "params": {}},
                "status": "ready",
            },
        ],
    }
    state = {**state, **policy_gate(state)}

    plan = planner_stub(state)["plan_ir"]
    steps = plan["steps"]
    tool_inputs = [(step["name"], step["inputs"]) for step in steps]

    assert ("get_stock_price", {"ticker": "GOOGL"}) in tool_inputs
    assert ("get_company_news", {"ticker": "GOOGL", "fast": True, "limit": 3}) in tool_inputs
    assert ("get_stock_price", {"ticker": "MSFT"}) in tool_inputs
    assert ("get_company_news", {"ticker": "MSFT", "fast": True, "limit": 3}) in tool_inputs
    assert any(step["name"] == "get_official_macro_releases" for step in steps)
    assert len(plan["tasks"]) == 5
    assert all(step.get("task_ids") for step in steps)
    assert {
        tuple(step.get("task_ids") or [])
        for step in steps
        if (step.get("inputs") or {}).get("ticker") == "GOOGL"
    } == {("task_1",), ("task_2",)}


def test_multitask_render_mentions_blocked_portfolio_without_hiding_ready_tasks():
    from backend.graph.nodes.render_stub import render_stub

    state = {
        "query": "谷歌新闻，然后微软新闻，最近有什么影响我的持仓？",
        "output_mode": "brief",
        "subject": {"subject_type": "company", "tickers": ["GOOGL"]},
        "operation": {"name": "fetch", "confidence": 0.8, "params": {}},
        "tasks": [
            {
                "id": "task_1",
                "subject_type": "company",
                "subject_label": "GOOGL",
                "tickers": ["GOOGL"],
                "operation": {"name": "fetch", "confidence": 0.8, "params": {}},
            },
            {
                "id": "task_2",
                "subject_type": "company",
                "subject_label": "MSFT",
                "tickers": ["MSFT"],
                "operation": {"name": "fetch", "confidence": 0.8, "params": {}},
            },
        ],
        "blocked_tasks": [
            {
                "id": "blocked_1",
                "subject_type": "portfolio",
                "operation": {"name": "portfolio_impact", "confidence": 0.0, "params": {}},
                "reason": "missing_portfolio_holdings",
                "question": "需要持仓列表。",
            }
        ],
        "plan_ir": {
            "steps": [
                {"id": "s1", "kind": "tool", "name": "get_company_news", "inputs": {"ticker": "GOOGL"}},
                {"id": "s2", "kind": "tool", "name": "get_company_news", "inputs": {"ticker": "MSFT"}},
            ]
        },
        "artifacts": {
            "step_results": {
                "s1": {"output": [{"title": "Google headline", "source": "test"}]},
                "s2": {"output": [{"title": "Microsoft headline", "source": "test"}]},
            }
        },
    }

    result = render_stub(state)
    draft = result["artifacts"]["draft_markdown"]

    assert "GOOGL" in draft
    assert "MSFT" in draft
    assert "Google headline" in draft
    assert "Microsoft headline" in draft
    assert "missing_portfolio_holdings" not in draft
    assert "持仓" in draft



# ==================== P2 weak fallback (vague-subject deixis) ====================

def test_weak_fallback_binds_active_symbol_when_query_uses_vague_deixis():
    """这只票/这家公司 + ui_context.active_symbol → 透明绑定 + 提示."""
    from backend.graph.nodes.understand_request import understand_request

    result = _run(
        understand_request(
            {
                "query": "这只票今天怎么了",
                "ui_context": {"active_symbol": "AAPL"},
                "output_mode": "brief",
                "trace": {},
            }
        )
    )
    understanding = result.get("understanding") or {}
    assert understanding.get("route") == "research"
    assert _task_ops(result) == [("company", ("AAPL",), "qa")]
    fallback = understanding.get("fallback_assumptions") or []
    assert any("AAPL" in s and "正在看" in s for s in fallback)


def test_weak_fallback_skipped_without_active_symbol():
    """同样的模糊 query 但没 active_symbol → 不兜底，走 clarify."""
    from backend.graph.nodes.understand_request import understand_request

    result = _run(
        understand_request(
            {
                "query": "这只票今天怎么了",
                "ui_context": {},
                "output_mode": "brief",
                "trace": {},
            }
        )
    )
    understanding = result.get("understanding") or {}
    assert understanding.get("route") == "clarify"
    assert result.get("tasks") == []


def test_weak_fallback_does_not_override_explicit_ticker():
    """显式提到 AAPL 时，active_symbol=GOOGL 不应改写为 GOOGL."""
    from backend.graph.nodes.understand_request import understand_request

    result = _run(
        understand_request(
            {
                "query": "帮我看苹果",
                "ui_context": {"active_symbol": "GOOGL"},
                "output_mode": "brief",
                "trace": {},
            }
        )
    )
    tickers = [t.get("tickers") for t in result.get("tasks") or []]
    assert tickers and tickers[0] == ["AAPL"], f"expected AAPL, got {tickers}"
    fallback = (result.get("understanding") or {}).get("fallback_assumptions") or []
    # 显式 ticker 不应触发弱兜底提示
    assert not any("正在看" in s for s in fallback)


def test_weak_fallback_does_not_fire_on_pure_greeting():
    """纯问候 + active_symbol 不应触发弱兜底（仍走 direct）."""
    from backend.graph.nodes.understand_request import understand_request

    result = _run(
        understand_request(
            {
                "query": "你好",
                "ui_context": {"active_symbol": "AAPL"},
                "output_mode": "brief",
                "trace": {},
            }
        )
    )
    understanding = result.get("understanding") or {}
    assert understanding.get("route") == "direct"
    assert result.get("tasks") == []
