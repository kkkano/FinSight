# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import re
import json

from backend.graph.earnings_intent import query_requests_earnings_price_impact
from backend.graph.capability_registry import select_agents_for_request
from backend.graph.coverage_validator import validate_plan_coverage_for_frames
from backend.graph.intent_contract import EXTERNAL_IMPACT_LIGHT_PROFILE, canonical_evidence_kinds
from backend.graph.request_task_contract import reply_contract_disallows_news
from backend.graph.state import GraphState
from backend.graph.plan_ir import PlanIR, PlanBudget, PlanSubject
from backend.graph.understanding_v2 import VALUATION_COMPARE_LIGHT_PROFILE, project_v2_tasks_to_legacy


_SEC_HOLDINGS_ENABLED_VALUES = {"1", "true", "yes", "on"}


def _sec_holdings_enabled() -> bool:
    return str(os.getenv("SEC_HOLDINGS_ENABLED") or "").strip().lower() in _SEC_HOLDINGS_ENABLED_VALUES


def _holder_cik_or_name_from_query(query: str) -> str:
    lowered = str(query or "").lower()
    if any(token in lowered for token in ("buffett", "berkshire")) or any(
        token in str(query or "") for token in ("巴菲特", "伯克希尔")
    ):
        return "Berkshire Hathaway"
    return ""


def planner_stub(state: GraphState) -> dict:
    """
    Phase 1 stub: produce a minimal PlanIR.
    Later phases will replace this with an LLM-constrained Planner.
    """
    raw_subject = state.get("subject")
    subject = raw_subject if isinstance(raw_subject, dict) else {}
    output_mode = state.get("output_mode") or "brief"
    query = (state.get("query") or "").strip()
    operation_obj = state.get("operation") if isinstance(state.get("operation"), dict) else {}
    operation = operation_obj.get("name") or "qa"
    operation_params = operation_obj.get("params") if isinstance(operation_obj.get("params"), dict) else {}
    news_disallowed = reply_contract_disallows_news(state)
    reply_contract = state.get("reply_contract") if isinstance(state.get("reply_contract"), dict) else {}
    source_constraints = (
        reply_contract.get("source_constraints")
        if isinstance(reply_contract.get("source_constraints"), dict)
        else {}
    )
    requires_links = bool(source_constraints.get("requires_links"))

    trace = state.get("trace") or {}

    policy = state.get("policy") or {}
    raw_budget = policy.get("budget") if isinstance(policy, dict) else None
    budget = PlanBudget.model_validate(raw_budget or {"max_rounds": 1, "max_tools": 0})
    allowed_tools = set((policy.get("allowed_tools") or []) if isinstance(policy, dict) else [])
    allowed_agents = set((policy.get("allowed_agents") or []) if isinstance(policy, dict) else [])
    raw_tasks = state.get("tasks")
    if not isinstance(raw_tasks, list):
        raw_tasks = project_v2_tasks_to_legacy(state.get("understanding_v2"))
    ready_tasks = [
        task for task in (raw_tasks if isinstance(raw_tasks, list) else [])
        if isinstance(task, dict) and str(task.get("status") or "ready").strip().lower() != "blocked"
    ]
    ready_task_id_set = {str(task.get("id") or "").strip() for task in ready_tasks if str(task.get("id") or "").strip()}
    raw_request_frames = state.get("request_frames")
    request_frames = [
        frame for frame in (raw_request_frames if isinstance(raw_request_frames, list) else [])
        if isinstance(frame, dict)
    ]
    if not request_frames and isinstance(state.get("request_frame"), dict):
        request_frames = [state["request_frame"]]

    steps: list[dict] = []
    step_index: dict[tuple[str, str, str], dict] = {}
    step_id = 1

    selection_payload = subject.get("selection_payload") if isinstance(subject, dict) else None
    if isinstance(selection_payload, list) and selection_payload:
        steps.append(
            {
                "id": f"s{step_id}",
                "kind": "llm",
                "name": "summarize_selection",
                "inputs": {"selection": selection_payload, "query": query},
                "why": "Selection 是高权重证据，先读/先总结以避免跑偏",
                "optional": False,
            }
        )
        step_id += 1
    else:
        selection_payload = []

    tickers = subject.get("tickers") if isinstance(subject, dict) else None
    primary_ticker = (tickers or [None])[0] if isinstance(tickers, list) else None
    subject_type = subject.get("subject_type") if isinstance(subject, dict) else None
    query_lower = query.lower()

    def _contains_any(tokens: tuple[str, ...]) -> bool:
        return any(token in query_lower for token in tokens)

    def _qa_needs_live_context() -> bool:
        if output_mode == "investment_report":
            return True
        if news_disallowed:
            return False
        return _contains_any(
            (
                "最新",
                "最近",
                "新闻",
                "消息",
                "今天",
                "现在",
                "实时",
                "股价",
                "价格",
                "涨跌",
                "财报",
                "指引",
                "latest",
                "recent",
                "news",
                "today",
                "current",
                "real-time",
                "realtime",
                "price",
                "earnings",
                "guidance",
            )
        )

    def _macro_query_for_task(task: dict) -> str:
        label = str(task.get("subject_label") or "").strip()
        if label and label != "宏观环境":
            return label
        return query

    deep_financial_tokens = (
        "deep report",
        "deep research",
        "longform",
        "filing",
        "10-k",
        "10-q",
        "earnings call",
        "transcript",
        "研报",
        "深度",
        "财报",
        "电话会",
    )
    is_deep_financial_report = output_mode == "investment_report" and (
        _contains_any(deep_financial_tokens) or "deep_search_agent" in allowed_agents
    )

    def _append_tool_step(
        name: str,
        inputs: dict,
        *,
        why: str,
        optional: bool = True,
        parallel_group: str | None = None,
        task_ids: list[str] | None = None,
    ) -> None:
        nonlocal step_id
        if name not in allowed_tools:
            return
        try:
            inputs_key = json.dumps(inputs, ensure_ascii=False, sort_keys=True, default=str)
        except Exception:
            inputs_key = str(sorted(inputs.items())) if isinstance(inputs, dict) else str(inputs)
        group_key = str(parallel_group or "")
        key = (name, inputs_key, group_key)
        normalized_task_ids = [str(task_id).strip() for task_id in (task_ids or []) if str(task_id).strip()]
        if not normalized_task_ids and isinstance(parallel_group, str) and parallel_group in ready_task_id_set:
            normalized_task_ids = [parallel_group]
        existing = step_index.get(key)
        if existing is not None:
            if optional is False:
                existing["optional"] = False
            if normalized_task_ids:
                merged = [
                    str(task_id).strip()
                    for task_id in (existing.get("task_ids") or [])
                    if str(task_id).strip()
                ]
                seen = set(merged)
                for task_id in normalized_task_ids:
                    if task_id in seen:
                        continue
                    seen.add(task_id)
                    merged.append(task_id)
                existing["task_ids"] = merged
                existing["task_id"] = merged[0]
            return
        step = {
            "id": f"s{step_id}",
            "kind": "tool",
            "name": name,
            "inputs": inputs,
            "why": why,
            "optional": optional,
        }
        if normalized_task_ids:
            step["task_ids"] = normalized_task_ids
            step["task_id"] = normalized_task_ids[0]
        if parallel_group:
            step["parallel_group"] = parallel_group
        steps.append(step)
        step_index[key] = step
        step_id += 1

    def _append_agent_step(
        name: str,
        inputs: dict,
        *,
        why: str,
        optional: bool = True,
        parallel_group: str | None = None,
        task_ids: list[str] | None = None,
    ) -> None:
        nonlocal step_id
        if name not in allowed_agents:
            return
        try:
            inputs_key = json.dumps(inputs, ensure_ascii=False, sort_keys=True, default=str)
        except Exception:
            inputs_key = str(sorted(inputs.items())) if isinstance(inputs, dict) else str(inputs)
        group_key = str(parallel_group or "")
        key = (f"agent:{name}", inputs_key, group_key)
        normalized_task_ids = [str(task_id).strip() for task_id in (task_ids or []) if str(task_id).strip()]
        if not normalized_task_ids and isinstance(parallel_group, str) and parallel_group in ready_task_id_set:
            normalized_task_ids = [parallel_group]
        existing = step_index.get(key)
        if existing is not None:
            if optional is False:
                existing["optional"] = False
            if normalized_task_ids:
                merged = [
                    str(task_id).strip()
                    for task_id in (existing.get("task_ids") or [])
                    if str(task_id).strip()
                ]
                seen = set(merged)
                for task_id in normalized_task_ids:
                    if task_id in seen:
                        continue
                    seen.add(task_id)
                    merged.append(task_id)
                existing["task_ids"] = merged
                existing["task_id"] = merged[0]
            return
        step = {
            "id": f"s{step_id}",
            "kind": "agent",
            "name": name,
            "inputs": inputs,
            "why": why,
            "optional": optional,
        }
        if normalized_task_ids:
            step["task_ids"] = normalized_task_ids
            step["task_id"] = normalized_task_ids[0]
        if parallel_group:
            step["parallel_group"] = parallel_group
        steps.append(step)
        step_index[key] = step
        step_id += 1

    def _task_operation_params(task: dict) -> dict:
        operation_obj = task.get("operation")
        if isinstance(operation_obj, dict) and isinstance(operation_obj.get("params"), dict):
            return operation_obj.get("params") or {}
        return {}

    def _task_required_evidence(task: dict) -> list[str]:
        params = _task_operation_params(task)
        required = params.get("required_evidence")
        if not isinstance(required, list):
            task_params = task.get("params")
            required = task_params.get("required_evidence") if isinstance(task_params, dict) else []
        if not isinstance(required, list):
            required = []
        if not required and len(ready_tasks) == 1 and isinstance(policy.get("required_evidence"), list):
            required = policy.get("required_evidence") or []
        return canonical_evidence_kinds([str(item) for item in required if str(item).strip()])

    def _append_evidence_steps_for_ticker(
        ticker: str,
        required_evidence: list[str],
        *,
        group: str,
        task_ids: list[str],
        evidence_profile: str = "",
    ) -> None:
        lightweight_external_impact = evidence_profile == EXTERNAL_IMPACT_LIGHT_PROFILE
        for kind in required_evidence:
            if kind == "price_snapshot":
                _append_tool_step(
                    "get_stock_price",
                    {"ticker": ticker},
                    why=f"{ticker} evidence contract: price snapshot.",
                    optional=False,
                    parallel_group=group,
                    task_ids=task_ids,
                )
            elif kind == "company_profile":
                _append_tool_step(
                    "get_company_info",
                    {"ticker": ticker},
                    why=f"{ticker} evidence contract: company profile.",
                    optional=False,
                    parallel_group=group,
                    task_ids=task_ids,
                )
            elif kind == "earnings_estimates":
                _append_tool_step(
                    "get_earnings_estimates",
                    {"ticker": ticker},
                    why=f"{ticker} evidence contract: earnings estimates.",
                    optional=False,
                    parallel_group=group,
                    task_ids=task_ids,
                )
                _append_tool_step(
                    "get_eps_revisions",
                    {"ticker": ticker},
                    why=f"{ticker} evidence contract: EPS revisions.",
                    optional=True,
                    parallel_group=group,
                    task_ids=task_ids,
                )
            elif kind == "fundamental_snapshot":
                _append_agent_step(
                    "fundamental_agent",
                    {"query": query, "ticker": ticker},
                    why=f"{ticker} evidence contract: fundamental snapshot.",
                    optional=False,
                    parallel_group=f"{group}_fundamental_agents" if group else "fundamental_agents",
                    task_ids=task_ids,
                )
            elif kind == "technical_snapshot":
                _append_tool_step(
                    "get_technical_snapshot",
                    {"ticker": ticker},
                    why=f"{ticker} evidence contract: technical snapshot.",
                    optional=False,
                    parallel_group=group,
                    task_ids=task_ids,
                )
                _append_agent_step(
                    "technical_agent",
                    {"query": query, "ticker": ticker},
                    why=f"{ticker} evidence contract: technical agent synthesis.",
                    optional=True,
                    parallel_group=f"{group}_technical_agents" if group else "technical_agents",
                    task_ids=task_ids,
                )
            elif kind == "news_context":
                _append_tool_step(
                    "get_company_news",
                    {"ticker": ticker},
                    why=f"{ticker} evidence contract: company news context.",
                    optional=True,
                    parallel_group=group,
                    task_ids=task_ids,
                )
                _append_tool_step(
                    "get_authoritative_media_news",
                    {"query": f"{ticker} {query}".strip(), "max_results": 6, "authoritative_only": False},
                    why=f"{ticker} evidence contract: authoritative media context.",
                    optional=True,
                    parallel_group=group,
                    task_ids=task_ids,
                )
                if not lightweight_external_impact:
                    _append_agent_step(
                        "news_agent",
                        {"query": query, "ticker": ticker},
                        why=f"{ticker} evidence contract: news agent synthesis.",
                        optional=True,
                        parallel_group=f"{group}_news_agents" if group else "news_agents",
                        task_ids=task_ids,
                    )
            elif kind == "risk_profile":
                positions = [{"ticker": ticker, "weight": 1.0}]
                _append_tool_step(
                    "analyze_historical_drawdowns",
                    {"ticker": ticker},
                    why=f"{ticker} evidence contract: drawdown risk.",
                    optional=True,
                    parallel_group=group,
                    task_ids=task_ids,
                )
                _append_tool_step(
                    "get_factor_exposure",
                    {"positions": positions, "lookback_days": 252},
                    why=f"{ticker} evidence contract: factor exposure.",
                    optional=True,
                    parallel_group=group,
                    task_ids=task_ids,
                )
                _append_tool_step(
                    "run_portfolio_stress_test",
                    {"positions": positions, "lookback_days": 252},
                    why=f"{ticker} evidence contract: stress test.",
                    optional=True,
                    parallel_group=group,
                    task_ids=task_ids,
                )
                if not lightweight_external_impact:
                    _append_agent_step(
                        "risk_agent",
                        {"query": query, "ticker": ticker},
                        why=f"{ticker} evidence contract: risk agent synthesis.",
                        optional=True,
                        parallel_group=f"{group}_risk_agents" if group else "risk_agents",
                        task_ids=task_ids,
                    )
            elif kind == "filing_context":
                _append_tool_step(
                    "get_sec_company_facts_quarterly",
                    {"ticker": ticker},
                    why=f"{ticker} evidence contract: quarterly company facts.",
                    optional=True,
                    parallel_group=group,
                    task_ids=task_ids,
                )
                _append_tool_step(
                    "get_sec_filings",
                    {"ticker": ticker, "forms": ["10-K", "10-Q"], "limit": 4},
                    why=f"{ticker} evidence contract: SEC filings.",
                    optional=True,
                    parallel_group=group,
                    task_ids=task_ids,
                )
                _append_tool_step(
                    "get_local_market_filings",
                    {"ticker": ticker, "limit": 5},
                    why=f"{ticker} evidence contract: local-market filings.",
                    optional=True,
                    parallel_group=group,
                    task_ids=task_ids,
                )
            elif kind == "transcript_context":
                _append_tool_step(
                    "get_earnings_call_transcripts",
                    {"ticker": ticker, "limit": 5},
                    why=f"{ticker} evidence contract: earnings call transcripts.",
                    optional=True,
                    parallel_group=group,
                    task_ids=task_ids,
                )
            elif kind == "event_calendar":
                _append_tool_step(
                    "get_event_calendar",
                    {"ticker": ticker},
                    why=f"{ticker} evidence contract: event calendar.",
                    optional=True,
                    parallel_group=group,
                    task_ids=task_ids,
                )
            elif kind == "options_derivatives":
                _append_tool_step(
                    "get_option_chain_metrics",
                    {"ticker": ticker},
                    why=f"{ticker} evidence contract: options metrics.",
                    optional=True,
                    parallel_group=group,
                    task_ids=task_ids,
                )
            elif kind == "holdings_ownership":
                if not _sec_holdings_enabled():
                    continue
                _append_tool_step(
                    "get_insider_transactions",
                    {"ticker": ticker, "days": 180, "limit": 50},
                    why=f"{ticker} evidence contract: public insider transactions.",
                    optional=True,
                    parallel_group=group,
                    task_ids=task_ids,
                )
                _append_tool_step(
                    "get_institution_holdings_by_ticker",
                    {"ticker": ticker, "limit": 50},
                    why=f"{ticker} evidence contract: institutional ownership holders.",
                    optional=False,
                    parallel_group=group,
                    task_ids=task_ids,
                )

    def _has_step(kind: str, name: str) -> bool:
        return any(step.get("kind") == kind and step.get("name") == name for step in steps)

    def _append_earnings_performance_steps(
        ticker: str,
        *,
        group: str | None = None,
        task_ids: list[str] | None = None,
    ) -> None:
        evidence_group = group or "earnings_evidence"
        _append_tool_step(
            "get_company_info",
            {"ticker": ticker},
            why=f"{ticker} 财报表现任务：补充公司基础信息，避免只列新闻标题。",
            optional=True,
            parallel_group=evidence_group,
            task_ids=task_ids,
        )
        _append_tool_step(
            "get_sec_company_facts_quarterly",
            {"ticker": ticker, "limit": 8},
            why=f"{ticker} 财报表现任务：读取季度营收、净利和 EPS 等事实指标。",
            optional=True,
            parallel_group=evidence_group,
            task_ids=task_ids,
        )
        _append_tool_step(
            "get_earnings_estimates",
            {"ticker": ticker},
            why=f"{ticker} 财报表现任务：补充盈利预期和下一季共识。",
            optional=True,
            parallel_group=evidence_group,
            task_ids=task_ids,
        )
        _append_tool_step(
            "get_eps_revisions",
            {"ticker": ticker},
            why=f"{ticker} 财报表现任务：补充 EPS 上修/下修趋势。",
            optional=True,
            parallel_group=evidence_group,
            task_ids=task_ids,
        )
        if not news_disallowed:
            _append_tool_step(
                "get_company_news",
                {"ticker": ticker},
                why=f"{ticker} 财报表现任务：补充近期财报新闻、指引和市场反应。",
                optional=True,
                parallel_group=evidence_group,
                task_ids=task_ids,
            )
            _append_tool_step(
                "get_authoritative_media_news",
                {"query": f"{ticker} latest earnings results", "max_results": 6, "authoritative_only": True},
                why=f"{ticker} 财报表现任务：用权威媒体交叉验证财报要点。",
                optional=True,
                parallel_group=evidence_group,
                task_ids=task_ids,
            )
            _append_tool_step(
                "get_earnings_call_transcripts",
                {"ticker": ticker, "limit": 3},
                why=f"{ticker} 财报表现任务：补充电话会 transcript 以验证管理层指引。",
                optional=True,
                parallel_group=evidence_group,
                task_ids=task_ids,
            )
        agent_group = f"{evidence_group}_agents"
        _append_agent_step(
            "fundamental_agent",
            {"query": query, "ticker": ticker},
            why=f"{ticker} 财报表现任务：运行 fundamental_agent 汇总财务表现、预期和质量风险。",
            optional=False,
            parallel_group=agent_group,
            task_ids=task_ids,
        )
        _append_agent_step(
            "news_agent",
            {"query": query, "ticker": ticker},
            why=f"{ticker} 财报表现任务：运行 news_agent 区分财报催化和噪音。",
            optional=True,
            parallel_group=agent_group,
            task_ids=task_ids,
        )

    def _append_earnings_impact_steps(
        ticker: str,
        *,
        group: str | None = None,
        task_ids: list[str] | None = None,
    ) -> None:
        evidence_group = group or "earnings_impact_evidence"
        _append_tool_step(
            "get_stock_price",
            {"ticker": ticker},
            why=f"{ticker} 财报影响股价任务：获取当前价格/涨跌幅作为市场反应锚点。",
            optional=False,
            parallel_group=evidence_group,
            task_ids=task_ids,
        )
        _append_tool_step(
            "analyze_historical_drawdowns",
            {"ticker": ticker},
            why=f"{ticker} 财报影响股价任务：补充历史波动和回撤风险。",
            optional=True,
            parallel_group=evidence_group,
            task_ids=task_ids,
        )
        _append_earnings_performance_steps(ticker, group=evidence_group, task_ids=task_ids)
        _append_agent_step(
            "risk_agent",
            {"query": query, "ticker": ticker},
            why=f"{ticker} 财报影响股价任务：运行 risk_agent 给出价格反应的证伪和回撤风险。",
            optional=True,
            parallel_group=f"{evidence_group}_agents",
            task_ids=task_ids,
        )

    def _task_id(task: dict) -> str:
        value = str(task.get("id") or "").strip()
        return value or f"task_{len(steps) + 1}"

    def _task_operation_name(task: dict) -> str:
        op = task.get("operation")
        if isinstance(op, dict):
            name = op.get("name")
            if isinstance(name, str) and name.strip():
                return name.strip()
        return "qa"

    def _task_operation_params(task: dict) -> dict:
        op = task.get("operation")
        if not isinstance(op, dict):
            return {}
        params = op.get("params")
        return params if isinstance(params, dict) else {}

    def _task_tickers(task: dict) -> list[str]:
        values = task.get("tickers")
        if not isinstance(values, list):
            return []
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            ticker = str(value or "").strip().upper()
            if not ticker or ticker in seen:
                continue
            seen.add(ticker)
            result.append(ticker)
        return result

    def _task_urls(task: dict) -> list[str]:
        params = _task_operation_params(task)
        candidates: list[object] = [
            params.get("url"),
            task.get("url"),
        ]
        raw_urls = params.get("urls")
        if isinstance(raw_urls, list):
            candidates.extend(raw_urls)
        result: list[str] = []
        seen: set[str] = set()
        for value in candidates:
            url = str(value or "").strip().rstrip(".,，。;；:：!?！？")
            if not url.startswith(("http://", "https://")) or url in seen:
                continue
            seen.add(url)
            result.append(url)
        return result[:3]

    def _plan_task_summary() -> list[dict]:
        rows: list[dict] = []
        for task in ready_tasks[:16]:
            task_id = str(task.get("id") or f"task_{len(rows) + 1}").strip()
            rows.append(
                {
                    "id": task_id or f"task_{len(rows) + 1}",
                    "subject_type": str(task.get("subject_type") or "unknown"),
                    "tickers": _task_tickers(task),
                    "operation": _task_operation_name(task),
                    "status": str(task.get("status") or "ready"),
                }
            )
        return rows

    def _plan_subject_payload() -> dict:
        return {
            "subject_type": str(subject.get("subject_type") or "unknown"),
            "tickers": [
                str(ticker).strip().upper()
                for ticker in (subject.get("tickers") if isinstance(subject.get("tickers"), list) else [])
                if str(ticker).strip()
            ],
            "selection_ids": list(subject.get("selection_ids") or []) if isinstance(subject.get("selection_ids"), list) else [],
            "selection_types": list(subject.get("selection_types") or []) if isinstance(subject.get("selection_types"), list) else [],
            "selection_payload": list(subject.get("selection_payload") or []) if isinstance(subject.get("selection_payload"), list) else [],
            "binding_tier": str(subject.get("binding_tier") or "none"),
            "is_comparison": subject.get("is_comparison") if isinstance(subject.get("is_comparison"), bool) else None,
        }

    def _compare_has_current_support(task: dict) -> bool:
        compare_tickers = set(_task_tickers(task))
        if not compare_tickers:
            return False
        current_ops = {"price", "fetch", "analyze_impact", "daily_brief", "technical", "investment_opinion", "earnings_impact", "earnings_performance"}
        for other in ready_tasks:
            if other is task:
                continue
            if _task_operation_name(other) not in current_ops:
                continue
            if compare_tickers.intersection(_task_tickers(other)):
                return True
        return False

    def _should_use_performance_compare(task: dict | None = None) -> bool:
        if output_mode == "investment_report":
            return True
        params = _task_operation_params(task or {})
        if bool(params.get("synthesis_only")):
            return False
        data_profile = str(params.get("data_profile") or params.get("comparison_data_profile") or "").strip().lower()
        if data_profile in {"research_synthesis", "synthesis_only"}:
            return False
        if data_profile in {"performance", "historical_performance"}:
            return True
        if data_profile in {
            "facet_evidence",
            "research_synthesis",
            "synthesis_only",
            VALUATION_COMPARE_LIGHT_PROFILE,
            "valuation_compare",
            "technical_compare",
            "earnings_price_impact",
            "investment_opinion_compare",
        }:
            return False
        if task is not None and _compare_has_current_support(task):
            return False
        return True

    def _append_company_task_steps(task: dict, *, group: str) -> None:
        op_name = _task_operation_name(task)
        params = _task_operation_params(task)
        tickers_for_task = _task_tickers(task)
        task_ids = [_task_id(task)]
        if op_name == "backtest":
            ticker = tickers_for_task[0] if tickers_for_task else primary_ticker
            strategy = str(params.get("strategy") or "ma_cross").strip() or "ma_cross"
            _append_tool_step(
                "run_strategy_backtest",
                {
                    "ticker": ticker or "",
                    "strategy": strategy,
                    "params": dict(params.get("strategy_params") or params.get("params") or {}),
                    "initial_cash": float(params.get("initial_cash") or 100000.0),
                    "t_plus_one": bool(params.get("t_plus_one", True)),
                },
                why="Backtest workflow action: execute the requested strategy and return performance metrics.",
                optional=False,
                parallel_group=group,
                task_ids=task_ids,
            )
            return
        if op_name == "compare" and len(tickers_for_task) >= 2:
            if _should_use_performance_compare(task):
                mapping = {ticker: ticker for ticker in tickers_for_task[:6]}
                _append_tool_step(
                    "get_performance_comparison",
                    {"tickers": mapping},
                    why="多标的对比任务：取标准化历史表现数据。",
                    optional=False,
                    parallel_group=group,
                    task_ids=task_ids,
                )
            if output_mode == "investment_report":
                for ticker in tickers_for_task[:6]:
                    _append_tool_step(
                        "get_stock_price",
                        {"ticker": ticker},
                        why=f"{ticker} 对比研报：补充当前价格作为报告锚点。",
                        optional=True,
                        parallel_group=group,
                        task_ids=task_ids,
                    )
                    _append_tool_step(
                        "get_company_news",
                        {"ticker": ticker},
                        why=f"{ticker} 对比研报：补充近期新闻用于事件解释。",
                        optional=True,
                        parallel_group=group,
                        task_ids=task_ids,
                    )
                    _append_tool_step(
                        "get_company_info",
                        {"ticker": ticker},
                        why=f"{ticker} 对比研报：补充公司基础信息。",
                        optional=True,
                        parallel_group=group,
                        task_ids=task_ids,
                    )
            return

        for ticker in tickers_for_task[:6]:
            live_qa = op_name == "qa" and _qa_needs_live_context()
            required_evidence = _task_required_evidence(task)
            if required_evidence:
                _append_evidence_steps_for_ticker(
                    ticker,
                    required_evidence,
                    group=group,
                    task_ids=task_ids,
                    evidence_profile=str(
                        params.get("evidence_profile") or params.get("budget_profile") or ""
                    ).strip().lower(),
                )
                continue
            if op_name == "earnings_impact" or query_requests_earnings_price_impact(query):
                _append_earnings_impact_steps(ticker, group=group, task_ids=task_ids)
                continue
            if op_name == "earnings_performance":
                _append_earnings_performance_steps(ticker, group=group, task_ids=task_ids)
                continue
            if op_name == "investment_opinion":
                valuation_focus = (
                    str(params.get("evidence_focus") or "").strip().lower() == "valuation"
                    or str(params.get("evidence_profile") or "").strip().lower() == VALUATION_COMPARE_LIGHT_PROFILE
                    or str(params.get("budget_profile") or "").strip().lower() == VALUATION_COMPARE_LIGHT_PROFILE
                )
                valuation_lightweight = (
                    str(params.get("evidence_profile") or "").strip().lower() == VALUATION_COMPARE_LIGHT_PROFILE
                    or str(params.get("budget_profile") or "").strip().lower() == VALUATION_COMPARE_LIGHT_PROFILE
                )
                _append_tool_step(
                    "get_stock_price",
                    {"ticker": ticker},
                    why=f"{ticker} 投资观点任务：获取当前价格/涨跌幅作为方向判断锚点。",
                    optional=False,
                    parallel_group=group,
                    task_ids=task_ids,
                )
                if valuation_focus:
                    _append_tool_step(
                        "get_company_info",
                        {"ticker": ticker},
                        why=f"{ticker} valuation evidence: add company and valuation context.",
                        optional=False,
                        parallel_group=group,
                        task_ids=task_ids,
                    )
                    _append_tool_step(
                        "get_earnings_estimates",
                        {"ticker": ticker},
                        why=f"{ticker} valuation evidence: add earnings expectations for multiple sanity.",
                        optional=False,
                        parallel_group=group,
                        task_ids=task_ids,
                    )
                    if not valuation_lightweight:
                        _append_agent_step(
                            "fundamental_agent",
                            {"query": query, "ticker": ticker},
                            why=f"{ticker} valuation evidence: run fundamental_agent for valuation support.",
                            optional=False,
                            parallel_group=f"{group}_valuation_agents" if group else "valuation_agents",
                            task_ids=task_ids,
                        )
                    continue
                _append_tool_step(
                    "get_technical_snapshot",
                    {"ticker": ticker},
                    why=f"{ticker} 投资观点任务：获取趋势、动量、支撑阻力等技术证据。",
                    optional=True,
                    parallel_group=group,
                    task_ids=task_ids,
                )
                _append_tool_step(
                    "get_company_news",
                    {"ticker": ticker},
                    why=f"{ticker} 投资观点任务：获取近期新闻和催化事件，避免只看价格。",
                    optional=True,
                    parallel_group=group,
                    task_ids=task_ids,
                )
                _append_tool_step(
                    "get_company_info",
                    {"ticker": ticker},
                    why=f"{ticker} 投资观点任务：补充公司基础信息和估值上下文。",
                    optional=True,
                    parallel_group=group,
                    task_ids=task_ids,
                )
                _append_tool_step(
                    "get_earnings_estimates",
                    {"ticker": ticker},
                    why=f"{ticker} 投资观点任务：补充盈利预期，避免只给消息面判断。",
                    optional=True,
                    parallel_group=group,
                    task_ids=task_ids,
                )
                _append_tool_step(
                    "get_eps_revisions",
                    {"ticker": ticker},
                    why=f"{ticker} 投资观点任务：补充 EPS 修正方向，判断基本面预期是否改善。",
                    optional=True,
                    parallel_group=group,
                    task_ids=task_ids,
                )
                _append_tool_step(
                    "analyze_historical_drawdowns",
                    {"ticker": ticker},
                    why=f"{ticker} 投资观点任务：补充历史回撤和波动风险。",
                    optional=True,
                    parallel_group=group,
                    task_ids=task_ids,
                )
                agent_group = f"{group}_opinion_agents" if group else "opinion_agents"
                _append_agent_step(
                    "technical_agent",
                    {"query": query, "ticker": ticker},
                    why=f"{ticker} 投资观点任务：运行 technical_agent 给出趋势、动量和关键价位。",
                    optional=False,
                    parallel_group=agent_group,
                    task_ids=task_ids,
                )
                _append_agent_step(
                    "fundamental_agent",
                    {"query": query, "ticker": ticker},
                    why=f"{ticker} 投资观点任务：运行 fundamental_agent 给出基本面和估值证据。",
                    optional=True,
                    parallel_group=agent_group,
                    task_ids=task_ids,
                )
                _append_agent_step(
                    "risk_agent",
                    {"query": query, "ticker": ticker},
                    why=f"{ticker} 投资观点任务：运行 risk_agent 给出回撤、波动和证伪风险。",
                    optional=True,
                    parallel_group=agent_group,
                    task_ids=task_ids,
                )
                _append_agent_step(
                    "news_agent",
                    {"query": query, "ticker": ticker},
                    why=f"{ticker} 投资观点任务：运行 news_agent 区分催化事件和噪音。",
                    optional=True,
                    parallel_group=agent_group,
                    task_ids=task_ids,
                )
                continue
            if op_name in {"price", "technical", "analyze_impact", "daily_brief"} or live_qa:
                _append_tool_step(
                    "get_stock_price",
                    {"ticker": ticker},
                    why=f"{ticker} 任务：获取价格/涨跌幅作为回答锚点。",
                    optional=op_name not in {"price", "technical"},
                    parallel_group=group,
                    task_ids=task_ids,
                )
            if op_name == "technical":
                _append_tool_step(
                    "get_technical_snapshot",
                    {"ticker": ticker},
                    why=f"{ticker} 技术面任务：获取技术指标快照。",
                    optional=False,
                    parallel_group=group,
                    task_ids=task_ids,
                )
                _append_agent_step(
                    "technical_agent",
                    {"query": query, "ticker": ticker},
                    why=f"{ticker} 技术面任务：运行 technical_agent 综合 K 线、报价、期权和情绪证据。",
                    optional=False,
                    parallel_group=group,
                    task_ids=task_ids,
                )
            if (op_name in {"fetch", "analyze_impact", "daily_brief"} or live_qa) and not news_disallowed:
                news_inputs = {"ticker": ticker}
                if output_mode == "brief":
                    news_inputs.update({"fast": True, "limit": 3})
                _append_tool_step(
                    "get_company_news",
                    news_inputs,
                    why=f"{ticker} 任务：获取相关新闻用于事件解释。",
                    optional=op_name not in {"fetch", "analyze_impact"},
                    parallel_group=group,
                    task_ids=task_ids,
                )
                if requires_links or bool(params.get("include_links")):
                    _append_tool_step(
                        "get_authoritative_media_news",
                        {
                            "query": f"{ticker} {query}".strip(),
                            "max_results": 6,
                            "authoritative_only": False,
                        },
                        why=f"{ticker} link-required news task: supplement article URLs from media/RSS feeds.",
                        optional=True,
                        parallel_group=group,
                        task_ids=task_ids,
                    )
            fast_brief_router_task = (
                output_mode == "brief"
                and str(task.get("reason") or "").strip()
                in {"conversation_router_task_hint", "conversation_router_task_hint_support"}
            )
            if (op_name == "analyze_impact" and not fast_brief_router_task) or (
                op_name == "qa" and output_mode == "investment_report"
            ):
                _append_tool_step(
                    "get_company_info",
                    {"ticker": ticker},
                    why=f"{ticker} 任务：补充公司基础信息，避免只看新闻标题。",
                    optional=True,
                    parallel_group=group,
                    task_ids=task_ids,
                )

    def _append_macro_task_steps(task: dict, *, group: str) -> None:
        op_name = _task_operation_name(task)
        if op_name == "qa" and output_mode != "investment_report":
            return
        task_ids = [_task_id(task)]
        task_query = _macro_query_for_task(task)
        _append_tool_step(
            "get_current_datetime",
            {},
            why="宏观任务：获取当前日期，防止把旧政策当成当前事实。",
            optional=True,
            parallel_group=group,
            task_ids=task_ids,
        )
        _append_tool_step(
            "get_official_macro_releases",
            {"query": query, "max_results": 8},
            why="宏观任务：优先检查官方宏观/央行发布。",
            optional=False,
            parallel_group=group,
            task_ids=task_ids,
        )
        _append_tool_step(
            "get_authoritative_media_news",
            {"query": task_query, "max_results": 6, "authoritative_only": True},
            why="宏观任务：用权威媒体交叉验证市场影响。",
            optional=True,
            parallel_group=group,
            task_ids=task_ids,
        )
        _append_tool_step(
            "search",
            {"query": task_query},
            why="宏观任务：补充开放搜索证据。",
            optional=True,
            parallel_group=group,
            task_ids=task_ids,
        )

    def _append_portfolio_task_steps(task: dict, *, group: str) -> None:
        task_ids = [_task_id(task)]
        tickers_for_task = _task_tickers(task)
        params = task.get("params") if isinstance(task.get("params"), dict) else {}
        raw_positions = params.get("positions") if isinstance(params.get("positions"), list) else []
        positions = [
            item
            for item in raw_positions
            if isinstance(item, dict) and str(item.get("ticker") or "").strip()
        ]
        if not positions and tickers_for_task:
            weight = round(1.0 / len(tickers_for_task), 4)
            positions = [{"ticker": ticker, "weight": weight} for ticker in tickers_for_task[:8]]
        if positions:
            _append_tool_step(
                "get_factor_exposure",
                {"positions": positions, "lookback_days": 252},
                why="组合任务：估算持仓因子暴露。",
                optional=True,
                parallel_group=group,
                task_ids=task_ids,
            )
            _append_tool_step(
                "run_portfolio_stress_test",
                {"positions": positions, "lookback_days": 252},
                why="组合任务：估算压力情景下的组合敏感性。",
                optional=True,
                parallel_group=group,
                task_ids=task_ids,
            )
        _append_tool_step(
            "search",
            {"query": query},
            why="组合任务：检索影响持仓的近期市场事件。",
            optional=True,
            parallel_group=group,
            task_ids=task_ids,
        )

    def _append_holdings_task_steps(task: dict, *, group: str) -> None:
        if not _sec_holdings_enabled():
            return
        if _task_operation_name(task) != "holdings":
            return

        task_ids = [_task_id(task)]
        tickers_for_task = _task_tickers(task)
        subject_for_task = str(task.get("subject_type") or "unknown").strip().lower()
        params = {**_task_operation_params(task)}
        task_params = task.get("params")
        if isinstance(task_params, dict):
            params.update(task_params)
        holder = str(params.get("holder_cik_or_name") or _holder_cik_or_name_from_query(query) or "").strip()
        quarter = str(params.get("quarter") or "").strip()

        if subject_for_task == "portfolio":
            raw_positions = params.get("positions") if isinstance(params.get("positions"), list) else []
            positions = [
                item
                for item in raw_positions
                if isinstance(item, dict) and str(item.get("ticker") or "").strip()
            ]
            if not positions and tickers_for_task:
                weight = round(1.0 / len(tickers_for_task), 4)
                positions = [{"ticker": ticker, "weight": weight} for ticker in tickers_for_task[:8]]
            if positions and holder:
                inputs: dict = {"positions": positions, "holder_cik_or_name": holder}
                if quarter:
                    inputs["quarter"] = quarter
                _append_tool_step(
                    "get_holdings_overlap",
                    inputs,
                    why="持仓重叠任务：用公开 13F 披露对比用户组合与机构持仓。",
                    optional=False,
                    parallel_group=group,
                    task_ids=task_ids,
                )
            elif holder:
                inputs = {"cik_or_name": holder, "limit": 100}
                if quarter:
                    inputs["quarter"] = quarter
                _append_tool_step(
                    "get_institutional_holdings",
                    inputs,
                    why="持仓任务缺少可对比组合：先读取机构公开 13F 持仓。",
                    optional=True,
                    parallel_group=group,
                    task_ids=task_ids,
                )
            return

        if subject_for_task in {"company", "index", "commodity"}:
            if holder:
                inputs = {"cik_or_name": holder, "limit": 100}
                if quarter:
                    inputs["quarter"] = quarter
                _append_tool_step(
                    "get_institutional_holdings",
                    inputs,
                    why="持仓任务：读取指定机构的公开 13F 持仓。",
                    optional=True,
                    parallel_group=group,
                    task_ids=task_ids,
                )
            for ticker in tickers_for_task[:6]:
                _append_tool_step(
                    "get_insider_transactions",
                    {"ticker": ticker, "days": 180, "limit": 50},
                    why=f"{ticker} 持仓任务：读取公开 Form 4 内部人交易披露。",
                    optional=True,
                    parallel_group=group,
                    task_ids=task_ids,
                )
                _append_tool_step(
                    "get_institution_holdings_by_ticker",
                    {"ticker": ticker, "limit": 50},
                    why=f"{ticker} 持仓任务：读取公开 13F 机构持有人线索。",
                    optional=True,
                    parallel_group=group,
                    task_ids=task_ids,
                )

    def _append_theme_task_steps(task: dict, *, group: str) -> None:
        task_ids = [_task_id(task)]
        task_query = str(task.get("subject_label") or query).strip() or query
        _append_tool_step(
            "get_current_datetime",
            {},
            why="主题任务：获取当前日期，限定近期事件语境。",
            optional=True,
            parallel_group=group,
            task_ids=task_ids,
        )
        _append_tool_step(
            "get_authoritative_media_news",
            {"query": query, "max_results": 6, "authoritative_only": True},
            why="主题任务：优先用权威媒体验证行业事件。",
            optional=True,
            parallel_group=group,
            task_ids=task_ids,
        )
        _append_tool_step(
            "search",
            {"query": task_query},
            why="主题任务：检索行业/主题的近期事件与影响。",
            optional=False,
            parallel_group=group,
            task_ids=task_ids,
        )

    def _append_document_task_steps(task: dict, *, group: str) -> None:
        urls = _task_urls(task)
        for url in urls:
            _append_tool_step(
                "fetch_url_content",
                {"url": url, "max_length": 6000},
                why="文档任务已给出 URL：读取页面正文后再作为证据使用。",
                optional=False,
                parallel_group=group,
                task_ids=[_task_id(task)],
            )
        if urls:
            return
        task_query = str(task.get("subject_label") or query).strip() or query
        _append_tool_step(
            "search",
            {"query": task_query},
            why="文档/新闻任务缺少可抓取 URL：用搜索补足来源线索。",
            optional=True,
            parallel_group=group,
            task_ids=[_task_id(task)],
        )

    def _frame_id(frame: dict, index: int) -> str:
        return str(frame.get("frame_id") or f"frame_{index}").strip() or f"frame_{index}"

    def _frame_subject(frame: dict) -> dict:
        subject_payload = frame.get("subject")
        return subject_payload if isinstance(subject_payload, dict) else {}

    def _frame_subject_type(frame: dict) -> str:
        return str(_frame_subject(frame).get("type") or "unknown").strip().lower() or "unknown"

    def _frame_tickers(frame: dict) -> list[str]:
        frame_subject = _frame_subject(frame)
        frame_tickers = frame_subject.get("tickers")
        if not isinstance(frame_tickers, list):
            return []
        normalized: list[str] = []
        seen: set[str] = set()
        for item in frame_tickers:
            ticker = str(item or "").strip().upper()
            if not ticker or ticker in seen:
                continue
            seen.add(ticker)
            normalized.append(ticker)
        return normalized

    def _frame_required_evidence(frame: dict) -> list[str]:
        raw_evidence = frame.get("evidence_obligations")
        return canonical_evidence_kinds(raw_evidence if isinstance(raw_evidence, list) else [])

    def _frame_required_results(frame: dict) -> list[str]:
        raw_results = frame.get("required_results")
        return [str(item).strip() for item in (raw_results if isinstance(raw_results, list) else []) if str(item).strip()]

    def _frame_workflow_action(frame: dict) -> dict:
        action = frame.get("workflow_action")
        return action if isinstance(action, dict) else {}

    def _frame_evidence_profile(frame: dict) -> str:
        raw_intent_contract = frame.get("intent_contract")
        intent_contract = raw_intent_contract if isinstance(raw_intent_contract, dict) else {}
        raw_legacy_operation = frame.get("legacy_operation")
        legacy_operation = raw_legacy_operation if isinstance(raw_legacy_operation, dict) else {}
        raw_legacy_params = legacy_operation.get("params")
        legacy_params = raw_legacy_params if isinstance(raw_legacy_params, dict) else {}
        return str(
            frame.get("evidence_profile")
            or frame.get("budget_profile")
            or intent_contract.get("budget_profile")
            or legacy_params.get("evidence_profile")
            or legacy_params.get("budget_profile")
            or ""
        ).strip()

    def _append_macro_frame_steps(frame: dict, *, group: str, task_id: str) -> None:
        frame_subject = _frame_subject(frame)
        label = str(frame_subject.get("label") or frame.get("subject_label") or "").strip()
        macro_query = label if label else query
        _append_tool_step(
            "get_current_datetime",
            {},
            why="Request frame macro evidence: current date guard.",
            optional=True,
            parallel_group=group,
            task_ids=[task_id],
        )
        _append_tool_step(
            "get_official_macro_releases",
            {"query": macro_query, "max_results": 8},
            why="Request frame macro evidence: official macro releases.",
            optional=False,
            parallel_group=group,
            task_ids=[task_id],
        )
        _append_tool_step(
            "get_authoritative_media_news",
            {"query": macro_query, "max_results": 6, "authoritative_only": True},
            why="Request frame macro evidence: authoritative market context.",
            optional=True,
            parallel_group=group,
            task_ids=[task_id],
        )
        _append_tool_step(
            "search",
            {"query": macro_query},
            why="Request frame macro evidence: supplemental search.",
            optional=True,
            parallel_group=group,
            task_ids=[task_id],
        )

    def _append_backtest_frame_steps(frame: dict, *, group: str, task_id: str) -> bool:
        required_results = set(_frame_required_results(frame))
        action = _frame_workflow_action(frame)
        action_name = str(action.get("name") or "").strip().lower()
        if action_name != "backtest" and "backtest_result" not in required_results:
            return False
        raw_slots = action.get("slots")
        slots = raw_slots if isinstance(raw_slots, dict) else {}
        frame_tickers = _frame_tickers(frame)
        ticker_for_backtest = (
            str(slots.get("ticker") or "").strip().upper()
            or (frame_tickers[0] if frame_tickers else "")
            or primary_ticker
            or ((tickers or [None])[0] if isinstance(tickers, list) else None)
            or ""
        )
        strategy = str(slots.get("strategy") or "ma_cross").strip() or "ma_cross"
        params = slots.get("strategy_params") or slots.get("params") or {}
        _append_tool_step(
            "run_strategy_backtest",
            {
                "ticker": ticker_for_backtest,
                "strategy": strategy,
                "params": dict(params if isinstance(params, dict) else {}),
                "initial_cash": float(slots.get("initial_cash") or 100000.0),
                "t_plus_one": bool(slots.get("t_plus_one", True)),
            },
            why="Request frame action result: run strategy backtest.",
            optional=False,
            parallel_group=group,
            task_ids=[task_id],
        )
        return True

    def _append_request_frame_steps() -> bool:
        if not request_frames:
            return False
        appended = False
        for index, frame in enumerate(request_frames[:16], 1):
            frame_id = _frame_id(frame, index)
            group = frame_id
            required_evidence = _frame_required_evidence(frame)
            required_results = _frame_required_results(frame)
            if not required_evidence and not required_results and not _frame_workflow_action(frame):
                continue

            if _append_backtest_frame_steps(frame, group=group, task_id=frame_id):
                appended = True

            if "macro_context" in required_evidence or _frame_subject_type(frame) == "macro":
                _append_macro_frame_steps(frame, group=group, task_id=frame_id)
                appended = True

            per_ticker_evidence = [kind for kind in required_evidence if kind != "macro_context"]
            if not per_ticker_evidence:
                continue
            frame_tickers = _frame_tickers(frame)
            if not frame_tickers and primary_ticker and _frame_subject_type(frame) in {"company", "index", "commodity"}:
                frame_tickers = [primary_ticker]
            for ticker in frame_tickers[:12]:
                _append_evidence_steps_for_ticker(
                    ticker,
                    per_ticker_evidence,
                    group=group,
                    task_ids=[frame_id],
                    evidence_profile=_frame_evidence_profile(frame),
                )
                appended = True
        return appended

    def _append_report_mode_enrichment_steps() -> None:
        if output_mode != "investment_report" or not primary_ticker:
            return

        deep_required = bool(is_deep_financial_report)
        task_ids = [
            str(task_id).strip()
            for task_id in sorted(ready_task_id_set)
            if str(task_id).strip()
        ] or None

        if not _has_step("tool", "get_stock_price"):
            _append_tool_step(
                "get_stock_price",
                {"ticker": primary_ticker},
                why="研报模式：补充当前价格作为估值、风险和结论锚点。",
                optional=True,
                parallel_group="report_evidence",
                task_ids=task_ids,
            )
        _append_tool_step(
            "analyze_historical_drawdowns",
            {"ticker": primary_ticker},
            why="研报模式：补充历史回撤信息用于风险章节。",
            optional=True,
            parallel_group="report_evidence",
            task_ids=task_ids,
        )

        if "get_local_market_filings" in allowed_tools:
            _append_tool_step(
                "get_local_market_filings",
                {"ticker": primary_ticker, "limit": 8},
                why="研报模式：补充本地交易所公告/定期报告证据。",
                optional=not deep_required,
                parallel_group="report_evidence",
                task_ids=task_ids,
            )
        else:
            _append_tool_step(
                "get_sec_filings",
                {"ticker": primary_ticker, "forms": "10-K,10-Q", "limit": 6},
                why="研报模式：补充 SEC EDGAR 10-K/10-Q filing evidence。",
                optional=not deep_required,
                parallel_group="report_evidence",
                task_ids=task_ids,
            )
            _append_tool_step(
                "get_sec_company_facts_quarterly",
                {"ticker": primary_ticker, "limit": 8},
                why="研报模式：补充 SEC CompanyFacts 季度财务指标。",
                optional=not deep_required,
                parallel_group="report_evidence",
                task_ids=task_ids,
            )
            _append_tool_step(
                "get_sec_material_events",
                {"ticker": primary_ticker, "limit": 5},
                why="研报模式：补充 SEC 8-K 重大事件证据。",
                optional=True,
                parallel_group="report_evidence",
                task_ids=task_ids,
            )

        if deep_required:
            _append_tool_step(
                "get_authoritative_media_news",
                {"query": f"{primary_ticker} earnings outlook", "max_results": 6, "authoritative_only": True},
                why="深度研报：强制补充权威媒体交叉验证。",
                optional=False,
                parallel_group="report_evidence",
                task_ids=task_ids,
            )
            _append_tool_step(
                "get_earnings_call_transcripts",
                {"ticker": primary_ticker, "limit": 5},
                why="深度研报：补充业绩电话会 transcript evidence。",
                optional=False,
                parallel_group="report_evidence",
                task_ids=task_ids,
            )

        policy_agent_selection = policy.get("agent_selection") if isinstance(policy, dict) else {}
        selected_agents: list[str] = []
        if isinstance(policy_agent_selection, dict):
            selected_agents = [
                str(name)
                for name in (policy_agent_selection.get("selected") or [])
                if isinstance(name, str) and name in allowed_agents
            ]
        if not selected_agents:
            ordered_agents = [
                "price_agent",
                "news_agent",
                "fundamental_agent",
                "technical_agent",
                "macro_agent",
                "risk_agent",
                "deep_search_agent",
            ]
            selected_agents = [name for name in ordered_agents if name in allowed_agents]
        agent_parallel_group = "report_agents" if len(selected_agents) > 1 else None
        for agent_name in selected_agents:
            _append_agent_step(
                agent_name,
                {"query": query, "ticker": primary_ticker},
                why=f"研报模式：运行 {agent_name} 产出结构化摘要和证据。",
                optional=True,
                parallel_group=agent_parallel_group,
                task_ids=task_ids,
            )

    def _append_understanding_task_steps() -> bool:
        if not ready_tasks:
            return False
        if len(ready_tasks) == 1:
            task = ready_tasks[0]
            subject_for_task = str(task.get("subject_type") or "unknown").strip().lower()
            if _task_operation_name(task) == "holdings":
                _append_holdings_task_steps(task, group=_task_id(task) or "task_1")
                return True
            if _task_urls(task) or subject_for_task in {"research_doc", "filing", "news_item", "news_set"}:
                _append_document_task_steps(task, group=_task_id(task) or "task_1")
                return True
            if subject_for_task in {"company", "index", "commodity"}:
                _append_company_task_steps(task, group=_task_id(task) or "task_1")
                return True
            if subject_for_task == "macro":
                _append_macro_task_steps(task, group=_task_id(task) or "task_1")
                return True
            if subject_for_task == "portfolio":
                _append_portfolio_task_steps(task, group=_task_id(task) or "task_1")
                return True
            if subject_for_task == "theme":
                _append_theme_task_steps(task, group=_task_id(task) or "task_1")
                return True
            return False
        if all(
            _task_subject_type in {"company", "index", "commodity"}
            and _task_operation_name(task) == "price"
            for task in ready_tasks
            for _task_subject_type in [str(task.get("subject_type") or "unknown").strip().lower()]
        ):
            for task in ready_tasks[:12]:
                _append_company_task_steps(task, group="price_quotes")
            return True
        for idx, task in enumerate(ready_tasks[:12], 1):
            subject_for_task = str(task.get("subject_type") or "unknown").strip().lower()
            group = (
                "brief_data"
                if output_mode == "brief" and subject_for_task in {"company", "index", "commodity"}
                else (_task_id(task) or f"task_{idx}")
            )
            if _task_operation_name(task) == "holdings":
                _append_holdings_task_steps(task, group=group)
            elif _task_urls(task):
                _append_document_task_steps(task, group=group)
            elif subject_for_task in {"company", "index", "commodity"}:
                _append_company_task_steps(task, group=group)
            elif subject_for_task == "macro":
                _append_macro_task_steps(task, group=group)
            elif subject_for_task == "portfolio":
                _append_portfolio_task_steps(task, group=group)
            elif subject_for_task == "theme":
                _append_theme_task_steps(task, group=group)
            elif subject_for_task in {"research_doc", "filing", "news_item", "news_set"}:
                _append_document_task_steps(task, group=group)
        return True

    used_request_frame_plan = _append_request_frame_steps()
    used_understanding_task_plan = False if used_request_frame_plan else _append_understanding_task_steps()

    if used_request_frame_plan or used_understanding_task_plan:
        _append_report_mode_enrichment_steps()
        task_sections = []
        if used_request_frame_plan:
            for index, frame in enumerate(request_frames[:8], 1):
                frame_subject = _frame_subject(frame)
                label = str(
                    frame_subject.get("label")
                    or ", ".join(_frame_tickers(frame))
                    or frame_subject.get("type")
                    or f"frame_{index}"
                )
                obligations = "+".join(_frame_required_evidence(frame) + _frame_required_results(frame)) or "contract"
                task_sections.append(f"{label}:{obligations}")
        for task in ready_tasks[:8]:
            label = str(task.get("subject_label") or ", ".join(_task_tickers(task)) or task.get("subject_type") or "任务")
            task_sections.append(f"{label}:{_task_operation_name(task)}")
        raw_plan = {
            "goal": query or "N/A",
            "subject": _plan_subject_payload(),
            "output_mode": output_mode,
            "tasks": _plan_task_summary(),
            "steps": steps,
            "synthesis": {"style": "structured", "sections": task_sections},
            "budget": budget.model_dump(),
        }
        try:
            plan = PlanIR.model_validate(raw_plan)
            coverage_validation = validate_plan_coverage_for_frames(
                request_frames=request_frames,
                plan_ir=plan.model_dump(),
            ) if request_frames else None
            trace.update(
                {
                    "planner": {
                        "type": "stub",
                        "validated": True,
                        "steps": len(plan.steps),
                        "operation": operation,
                        "understanding_task_count": len(ready_tasks),
                        "request_frame_count": len(request_frames),
                        "request_frame_driven": used_request_frame_plan,
                    }
                }
            )
            if coverage_validation is not None:
                trace["coverage_validator"] = coverage_validation
            return {"plan_ir": plan.model_dump(), "trace": trace}
        except Exception as exc:
            fallback = PlanIR(
                goal=query or "N/A",
                subject=PlanSubject(subject_type="unknown"),
                output_mode="brief",
                steps=[],
                budget=PlanBudget(max_rounds=1, max_tools=0),
            )
            trace.update(
                {
                    "planner": {
                        "type": "stub",
                        "validated": False,
                        "fallback": True,
                        "error": str(exc),
                    }
                }
            )
            return {"plan_ir": fallback.model_dump(), "trace": trace}

    if subject_type == "macro":
        _append_tool_step(
            "get_current_datetime",
            {},
            why="宏观/主题问题先获取当前日期，避免把旧政策路径当成当前事实。",
            optional=True,
        )
        _append_tool_step(
            "get_official_macro_releases",
            {"query": query, "max_results": 8},
            why="宏观/主题问题优先检索官方宏观发布与央行材料。",
            optional=True,
        )
        _append_tool_step(
            "get_authoritative_media_news",
            {"query": query, "max_results": 6, "authoritative_only": True},
            why="补充权威媒体对宏观路径和市场估值影响的交叉验证。",
            optional=True,
        )
        _append_tool_step(
            "search",
            {"query": query},
            why="补充开放搜索证据，用于覆盖主题研究中未被官方发布直接解释的市场影响。",
            optional=True,
        )

    # Morning brief: per-ticker price + news in parallel.
    if operation == "morning_brief":
        brief_tickers = [t for t in (tickers if isinstance(tickers, list) else []) if isinstance(t, str) and t.strip()]
        if not brief_tickers and isinstance(primary_ticker, str) and primary_ticker.strip():
            brief_tickers = [primary_ticker]
        for ticker in brief_tickers[:6]:
            if "get_stock_price" in allowed_tools:
                steps.append(
                    {
                        "id": f"s{step_id}",
                        "kind": "tool",
                        "name": "get_stock_price",
                        "inputs": {"ticker": ticker},
                        "parallel_group": "brief_data",
                        "why": f"晨报：获取 {ticker} 最新价格",
                        "optional": False,
                    }
                )
                step_id += 1
            if "get_company_news" in allowed_tools:
                steps.append(
                    {
                        "id": f"s{step_id}",
                        "kind": "tool",
                        "name": "get_company_news",
                        "inputs": {"ticker": ticker, "fast": True, "limit": 3},
                        "parallel_group": "brief_data",
                        "why": f"晨报：获取 {ticker} 最新新闻",
                        "optional": False,
                    }
                )
                step_id += 1
        if "get_current_datetime" in allowed_tools:
            steps.append(
                {
                    "id": f"s{step_id}",
                    "kind": "tool",
                    "name": "get_current_datetime",
                    "inputs": {},
                    "why": "晨报：获取当前日期时间用于报告标题",
                    "optional": True,
                }
            )
            step_id += 1

    if operation == "screen":
        screen_inputs = {
            "market": str((state.get("ui_context") or {}).get("market") or "US").upper(),
            "filters": {},
            "limit": 20,
            "page": 1,
            "sort_by": "marketCap",
            "sort_order": "desc",
        }
        if "screen_stocks" in allowed_tools:
            steps.append(
                {
                    "id": f"s{step_id}",
                    "kind": "tool",
                    "name": "screen_stocks",
                    "inputs": screen_inputs,
                    "why": "筛选类请求直接调用 screener 工具生成候选池。",
                    "optional": False,
                }
            )
            step_id += 1

    if operation == "cn_market":
        _append_tool_step(
            "get_cn_market_fund_flow",
            {"limit": 20},
            why="A股市场请求先给出资金流向快照。",
            optional=False,
        )
        _append_tool_step(
            "get_cn_market_northbound",
            {"limit": 20},
            why="补充北向资金维度。",
            optional=True,
        )
        _append_tool_step(
            "get_cn_limit_board",
            {"limit": 20},
            why="补充涨跌停板块异动。",
            optional=True,
        )
        _append_tool_step(
            "get_cn_lhb",
            {"limit": 20},
            why="补充龙虎榜交易信息。",
            optional=True,
        )
        _append_tool_step(
            "get_cn_concept_map",
            {"keyword": "", "limit": 20},
            why="补充概念板块信息。",
            optional=True,
        )

    if operation == "backtest":
        ticker_for_backtest = primary_ticker or ((tickers or [None])[0] if isinstance(tickers, list) else None) or ""
        _append_tool_step(
            "run_strategy_backtest",
            {
                "ticker": ticker_for_backtest,
                "strategy": str(operation_params.get("strategy") or "ma_cross").strip() or "ma_cross",
                "params": dict(operation_params.get("strategy_params") or operation_params.get("params") or {}),
                "initial_cash": float(operation_params.get("initial_cash") or 100000.0),
                "t_plus_one": bool(operation_params.get("t_plus_one", True)),
            },
            why="回测类请求调用策略回测工具并返回指标与交易明细。",
            optional=False,
        )

    # Rule-based minimal plan (Phase 3 scaffolding).
    if operation == "fetch" and primary_ticker and "get_company_news" in allowed_tools:
        steps.append(
            {
                "id": f"s{step_id}",
                "kind": "tool",
                "name": "get_company_news",
                "inputs": {"ticker": primary_ticker},
                "why": "获取标的最新新闻用于后续解读/对话",
                "optional": True,
            }
        )
        step_id += 1

    if operation == "compare":
        tickers_list = tickers if isinstance(tickers, list) else []
        tickers_list = [t for t in tickers_list if isinstance(t, str) and t.strip()]
        if len(tickers_list) >= 2 and "get_performance_comparison" in allowed_tools and _should_use_performance_compare(None):
            mapping = {t: t for t in tickers_list[:6]}
            steps.append(
                {
                    "id": f"s{step_id}",
                    "kind": "tool",
                    "name": "get_performance_comparison",
                    "inputs": {"tickers": mapping},
                    "why": "对比多标的 YTD/1Y 表现，作为对比分析的第一性数据",
                    "optional": False,
                }
            )
            step_id += 1
        if output_mode == "investment_report":
            for ticker in tickers_list[:6]:
                _append_tool_step(
                    "get_stock_price",
                    {"ticker": ticker},
                    why=f"{ticker} 对比研报：补充当前价格作为报告锚点。",
                    optional=True,
                )
                _append_tool_step(
                    "get_company_news",
                    {"ticker": ticker},
                    why=f"{ticker} 对比研报：补充近期新闻用于事件解释。",
                    optional=True,
                )
                _append_tool_step(
                    "get_company_info",
                    {"ticker": ticker},
                    why=f"{ticker} 对比研报：补充公司基础信息。",
                    optional=True,
                )

    if operation == "earnings_impact" and primary_ticker:
        _append_earnings_impact_steps(primary_ticker)

    if operation == "earnings_performance" and primary_ticker:
        _append_earnings_performance_steps(primary_ticker)

    if operation in ("price", "technical") and primary_ticker and "get_stock_price" in allowed_tools:
        steps.append(
            {
                "id": f"s{step_id}",
                "kind": "tool",
                "name": "get_stock_price",
                "inputs": {"ticker": primary_ticker},
                "why": "获取最新价格作为分析锚点",
                "optional": False,
            }
        )
        step_id += 1

    if operation == "technical" and primary_ticker and "get_technical_snapshot" in allowed_tools:
        steps.append(
            {
                "id": f"s{step_id}",
                "kind": "tool",
                "name": "get_technical_snapshot",
                "inputs": {"ticker": primary_ticker},
                "why": "计算 MA/RSI/MACD 等技术指标用于技术面分析",
                "optional": False,
            }
        )
        step_id += 1

    if subject_type in ("company",) and primary_ticker and "get_company_info" in allowed_tools and operation in (
        "summarize",
        "analyze_impact",
        "generate_report",
    ):
        steps.append(
            {
                "id": f"s{step_id}",
                "kind": "tool",
                "name": "get_company_info",
                "inputs": {"ticker": primary_ticker},
                "why": "补齐公司基础信息，便于解释新闻/财务信息的语境",
                "optional": True,
            }
        )
        step_id += 1

    # Keyword routing for new tools (stub mode fallback).
    normalized_tickers = [
        str(t).strip().upper()
        for t in (tickers if isinstance(tickers, list) else [])
        if isinstance(t, str) and str(t).strip()
    ]
    if not normalized_tickers and isinstance(primary_ticker, str) and primary_ticker.strip():
        normalized_tickers = [primary_ticker.strip().upper()]

    if primary_ticker and _contains_any(
        (
            "eps",
            "earnings estimate",
            "earnings estimates",
            "earnings revision",
            "eps revision",
            "consensus estimate",
            "guidance",
        )
    ):
        _append_tool_step(
            "get_earnings_estimates",
            {"ticker": primary_ticker},
            why="关键词命中盈利预期，补充 forward EPS 与预期分歧数据。",
        )
        _append_tool_step(
            "get_eps_revisions",
            {"ticker": primary_ticker},
            why="关键词命中 EPS 修正，补充上修/下修趋势信号。",
        )

    if primary_ticker and _contains_any(
        (
            "option",
            "options",
            "implied volatility",
            " iv ",
            " pcr ",
            "put/call",
            "put call ratio",
            "skew",
            "vol smile",
        )
    ):
        _append_tool_step(
            "get_option_chain_metrics",
            {"ticker": primary_ticker},
            why="关键词命中期权衍生指标，补充 IV/PCR/Skew。",
        )

    if primary_ticker and _contains_any(
        (
            "sec filing",
            "sec filings",
            "edgar",
            "10-k",
            "10-q",
            "filing history",
            "annual report filing",
            "quarterly filing",
            "regulatory filing",
        )
    ):
        _append_tool_step(
            "get_sec_filings",
            {"ticker": primary_ticker, "forms": "10-K,10-Q,8-K", "limit": 12},
            why="关键词命中监管披露需求，补充 SEC EDGAR 披露历史。",
        )

    if primary_ticker and _contains_any(
        (
            "material event",
            "material events",
            "8-k",
            "current report",
            "major event filing",
        )
    ):
        _append_tool_step(
            "get_sec_material_events",
            {"ticker": primary_ticker, "limit": 10},
            why="关键词命中重大事件披露需求，补充 SEC 8-K 信息。",
        )

    if primary_ticker and _contains_any(
        (
            "risk factor",
            "risk factors",
            "item 1a",
            "1a risk",
        )
    ):
        _append_tool_step(
            "get_sec_risk_factors",
            {"ticker": primary_ticker},
            why="关键词命中风险因子分析，从最新 10-K/10-Q 提取 Item 1A 摘要。",
        )

    if normalized_tickers and _contains_any(
        (
            "factor exposure",
            "stress test",
            "scenario shock",
            "volatility shock",
            "drawdown shock",
            "beta exposure",
            "risk factor",
        )
    ):
        weight = round(1.0 / len(normalized_tickers), 4)
        positions = [{"ticker": ticker, "weight": weight} for ticker in normalized_tickers[:6]]
        _append_tool_step(
            "get_factor_exposure",
            {"positions": positions, "lookback_days": 252},
            why="关键词命中因子暴露分析，生成组合 beta 与因子敞口。",
        )
        _append_tool_step(
            "run_portfolio_stress_test",
            {"positions": positions, "lookback_days": 252},
            why="关键词命中压力测试，生成情景冲击下的收益敏感性。",
        )

    if primary_ticker and _contains_any(
        (
            "event calendar",
            "earnings calendar",
            "earnings date",
            "dividend",
            "ex-dividend",
            "macro event",
            "fomc",
            "cpi",
            "payroll",
            "nfp",
            "calendar",
        )
    ):
        _append_tool_step(
            "get_event_calendar",
            {"ticker": primary_ticker, "days_ahead": 30},
            why="关键词命中事件日历，补充财报/分红/宏观事件时间点。",
        )

    if _contains_any(
        (
            "source reliability",
            "reliability score",
            "credible source",
            "news source",
            "rumor",
            "可信",
            "信源",
            "来源可靠",
        )
    ):
        reliability_inputs: dict[str, str] = {}
        url_match = re.search(r"https?://[^\s]+", query)
        if url_match:
            reliability_inputs["url"] = url_match.group(0).rstrip(".,)")
        for source_hint in ("reuters", "bloomberg", "wsj", "ft", "cnbc", "marketwatch", "seekingalpha"):
            if source_hint in query_lower:
                reliability_inputs["source"] = source_hint
                break
        _append_tool_step(
            "score_news_source_reliability",
            reliability_inputs,
            why="关键词命中信源可靠度评估，补充来源可信度分级。",
        )

    # Report mode can expand information gathering, but should remain minimal by default.
    if output_mode == "investment_report" and primary_ticker:
        if "get_stock_price" in allowed_tools:
            steps.append(
                {
                    "id": f"s{step_id}",
                    "kind": "tool",
                    "name": "get_stock_price",
                    "inputs": {"ticker": primary_ticker},
                    "why": "研报模式补充当前价格与估值/风险叙述的锚点",
                    "optional": True,
                }
            )
            step_id += 1
        if "analyze_historical_drawdowns" in allowed_tools:
            steps.append(
                {
                    "id": f"s{step_id}",
                    "kind": "tool",
                    "name": "analyze_historical_drawdowns",
                    "inputs": {"ticker": primary_ticker},
                    "why": "研报模式补充历史回撤信息用于风险章节",
                    "optional": True,
                }
            )
            step_id += 1
        if "get_local_market_filings" in allowed_tools:
            steps.append(
                {
                    "id": f"s{step_id}",
                    "kind": "tool",
                    "name": "get_local_market_filings",
                    "inputs": {"ticker": primary_ticker, "limit": 8},
                    "why": "Report mode: add CN/HK local market disclosures for non-US issuers.",
                    "optional": True,
                }
            )
            step_id += 1
        else:
            if "get_sec_filings" in allowed_tools:
                steps.append(
                    {
                        "id": f"s{step_id}",
                        "kind": "tool",
                        "name": "get_sec_filings",
                        "inputs": {"ticker": primary_ticker, "forms": "10-K,10-Q", "limit": 6},
                        "why": "Report mode: add SEC EDGAR 10-K/10-Q filing evidence.",
                        "optional": True,
                    }
                )
                step_id += 1
            if "get_sec_company_facts_quarterly" in allowed_tools:
                steps.append(
                    {
                        "id": f"s{step_id}",
                        "kind": "tool",
                        "name": "get_sec_company_facts_quarterly",
                        "inputs": {"ticker": primary_ticker, "limit": 8},
                        "why": "Report mode: add SEC CompanyFacts quarterly financial metrics.",
                        "optional": True,
                    }
                )
                step_id += 1
            if "get_sec_material_events" in allowed_tools:
                steps.append(
                    {
                        "id": f"s{step_id}",
                        "kind": "tool",
                        "name": "get_sec_material_events",
                        "inputs": {"ticker": primary_ticker, "limit": 5},
                        "why": "Report mode: add SEC 8-K material events as event evidence.",
                        "optional": True,
                    }
                )
                step_id += 1

        if is_deep_financial_report and "get_authoritative_media_news" in allowed_tools:
            steps.append(
                {
                    "id": f"s{step_id}",
                    "kind": "tool",
                    "name": "get_authoritative_media_news",
                    "inputs": {"query": f"{primary_ticker} earnings outlook", "max_results": 6, "authoritative_only": True},
                    "why": "Deep financial report: force authoritative media retrieval step.",
                    "optional": True,
                }
            )
            step_id += 1

        if is_deep_financial_report and "get_earnings_call_transcripts" in allowed_tools:
            steps.append(
                {
                    "id": f"s{step_id}",
                    "kind": "tool",
                    "name": "get_earnings_call_transcripts",
                    "inputs": {"ticker": primary_ticker, "limit": 5},
                    "why": "Deep financial report: add free earnings-call transcript evidence.",
                    "optional": True,
                }
            )
            step_id += 1

        all_agents = sorted(allowed_agents)
        policy_agent_selection = policy.get("agent_selection") if isinstance(policy, dict) else {}
        force_all_agents = bool(policy.get("force_all_agents")) if isinstance(policy, dict) else False
        if isinstance(policy_agent_selection, dict):
            force_all_agents = force_all_agents or bool(policy_agent_selection.get("force_all_agents"))
        dashboard_forced = bool(policy_agent_selection.get("forced_by_dashboard")) if isinstance(policy_agent_selection, dict) else False
        selected_agents: list[str] = []

        if force_all_agents:
            ordered = [
                "price_agent",
                "news_agent",
                "fundamental_agent",
                "technical_agent",
                "macro_agent",
                "risk_agent",
                "deep_search_agent",
            ]
            selected_agents = [name for name in ordered if name in allowed_agents]
            max_agents = len(selected_agents)
        elif dashboard_forced:
            ordered = [
                "price_agent",
                "news_agent",
                "fundamental_agent",
                "technical_agent",
                "macro_agent",
                "risk_agent",
                "deep_search_agent",
            ]
            selected_agents = [name for name in ordered if name in allowed_agents]
            max_agents = len(selected_agents)
        else:
            try:
                max_agents = int((os.getenv("LANGGRAPH_REPORT_MAX_AGENTS") or "4").strip())
            except Exception:
                max_agents = 4
            max_agents = max(1, min(max_agents, len(all_agents))) if all_agents else 0
            try:
                min_agents = int((os.getenv("LANGGRAPH_REPORT_MIN_AGENTS") or "2").strip())
            except Exception:
                min_agents = 2
            min_agents = max(1, min(min_agents, max_agents)) if max_agents else 0

            if all_agents and max_agents > 0:
                selected = select_agents_for_request(
                    state,
                    all_agents,
                    max_agents=max_agents,
                    min_agents=min_agents,
                )
                selected_agents = [str(name) for name in (selected.get("selected") or []) if isinstance(name, str) and name]

        ui_context = state.get("ui_context") if isinstance(state.get("ui_context"), dict) else {}
        analysis_depth = str((ui_context or {}).get("analysis_depth") or "").strip().lower()
        if analysis_depth == "report":
            selected_agents = [name for name in selected_agents if name != "deep_search_agent"]
        elif analysis_depth == "deep_research":
            if "deep_search_agent" in all_agents and "deep_search_agent" not in selected_agents:
                if not force_all_agents and max_agents > 0 and len(selected_agents) >= max_agents:
                    if max_agents == 1:
                        selected_agents = ["deep_search_agent"]
                    else:
                        selected_agents = selected_agents[: max_agents - 1] + ["deep_search_agent"]
                else:
                    selected_agents.append("deep_search_agent")

        # In report mode, run score-selected expert agents for richer cards (ReportView).
        # All report agents share the same parallel_group so the executor
        # runs them concurrently via asyncio.gather.
        agent_parallel_group = "report_agents" if len(selected_agents) > 1 else None

        for agent_name in selected_agents:
            if agent_name not in allowed_agents:
                continue
            steps.append(
                {
                    "id": f"s{step_id}",
                    "kind": "agent",
                    "name": agent_name,
                    "inputs": {"query": query, "ticker": primary_ticker},
                    "parallel_group": agent_parallel_group,
                    "why": f"研报模式：运行 {agent_name} 产出结构化摘要+证据（用于卡片展示）",
                    "optional": True,
                }
            )
            step_id += 1

    if output_mode == "investment_report" and subject_type == "macro" and not primary_ticker:
        policy_agent_selection = policy.get("agent_selection") if isinstance(policy, dict) else {}
        required_agents = []
        if isinstance(policy_agent_selection, dict):
            required_agents = [str(name) for name in (policy_agent_selection.get("required") or []) if isinstance(name, str)]
        ordered_agents = ["macro_agent", "news_agent", "deep_search_agent"]
        selected_agents = [name for name in ordered_agents if name in allowed_agents]
        if not selected_agents and "macro_agent" in allowed_agents:
            selected_agents = ["macro_agent"]
        agent_parallel_group = "report_agents" if len(selected_agents) > 1 else None

        for agent_name in selected_agents:
            steps.append(
                {
                    "id": f"s{step_id}",
                    "kind": "agent",
                    "name": agent_name,
                    "inputs": {"query": query, "ticker": ""},
                    "parallel_group": agent_parallel_group,
                    "why": f"宏观/主题研报模式：运行 {agent_name} 产出结构化摘要与证据。",
                    "optional": agent_name not in required_agents,
                }
            )
            step_id += 1

    raw_plan = {
        "goal": query or "N/A",
        "subject": _plan_subject_payload(),
        "output_mode": output_mode,
        "tasks": _plan_task_summary(),
        "steps": steps,
        "synthesis": {"style": "concise", "sections": []},
        "budget": budget.model_dump(),
    }

    try:
        plan = PlanIR.model_validate(raw_plan)
        coverage_validation = validate_plan_coverage_for_frames(
            request_frames=request_frames,
            plan_ir=plan.model_dump(),
        ) if request_frames else None
        trace.update(
            {
                "planner": {
                    "type": "stub",
                    "validated": True,
                    "steps": len(plan.steps),
                    "operation": operation,
                }
            }
        )
        if coverage_validation is not None:
            trace["coverage_validator"] = coverage_validation
        return {"plan_ir": plan.model_dump(), "trace": trace}
    except Exception as exc:
        fallback = PlanIR(
            goal=query or "N/A",
            subject=PlanSubject(subject_type="unknown"),
            output_mode="brief",
            steps=[],
            budget=PlanBudget(max_rounds=1, max_tools=0),
        )
        trace.update(
            {
                "planner": {
                    "type": "stub",
                    "validated": False,
                    "fallback": True,
                    "error": str(exc),
                }
            }
        )
        return {"plan_ir": fallback.model_dump(), "trace": trace}
