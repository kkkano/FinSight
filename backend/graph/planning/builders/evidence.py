# -*- coding: utf-8 -*-
# 机械拆分自 backend/graph/nodes/planner_stub.py（WP3 Task2，零行为变更）。
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
from backend.graph.planning.steps import _append_agent_step, _append_tool_step
from backend.graph.planning.util import _sec_holdings_enabled


def _append_evidence_steps_for_ticker(ctx, 
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
            _append_tool_step(ctx, 
                "get_stock_price",
                {"ticker": ticker},
                why=f"{ticker} evidence contract: price snapshot.",
                optional=False,
                parallel_group=group,
                task_ids=task_ids,
            )
        elif kind == "company_profile":
            _append_tool_step(ctx, 
                "get_company_info",
                {"ticker": ticker},
                why=f"{ticker} evidence contract: company profile.",
                optional=False,
                parallel_group=group,
                task_ids=task_ids,
            )
        elif kind == "earnings_estimates":
            _append_tool_step(ctx, 
                "get_earnings_estimates",
                {"ticker": ticker},
                why=f"{ticker} evidence contract: earnings estimates.",
                optional=False,
                parallel_group=group,
                task_ids=task_ids,
            )
            _append_tool_step(ctx, 
                "get_eps_revisions",
                {"ticker": ticker},
                why=f"{ticker} evidence contract: EPS revisions.",
                optional=True,
                parallel_group=group,
                task_ids=task_ids,
            )
        elif kind == "fundamental_snapshot":
            _append_agent_step(ctx, 
                "fundamental_agent",
                {"query": ctx.query, "ticker": ticker},
                why=f"{ticker} evidence contract: fundamental snapshot.",
                optional=False,
                parallel_group=f"{group}_fundamental_agents" if group else "fundamental_agents",
                task_ids=task_ids,
            )
        elif kind == "technical_snapshot":
            _append_tool_step(ctx, 
                "get_technical_snapshot",
                {"ticker": ticker},
                why=f"{ticker} evidence contract: technical snapshot.",
                optional=False,
                parallel_group=group,
                task_ids=task_ids,
            )
            _append_agent_step(ctx, 
                "technical_agent",
                {"query": ctx.query, "ticker": ticker},
                why=f"{ticker} evidence contract: technical agent synthesis.",
                optional=True,
                parallel_group=f"{group}_technical_agents" if group else "technical_agents",
                task_ids=task_ids,
            )
        elif kind == "news_context":
            _append_tool_step(ctx, 
                "get_company_news",
                {"ticker": ticker},
                why=f"{ticker} evidence contract: company news context.",
                optional=True,
                parallel_group=group,
                task_ids=task_ids,
            )
            _append_tool_step(ctx, 
                "get_authoritative_media_news",
                {"query": f"{ticker} {ctx.query}".strip(), "max_results": 6, "authoritative_only": False},
                why=f"{ticker} evidence contract: authoritative media context.",
                optional=True,
                parallel_group=group,
                task_ids=task_ids,
            )
            if not lightweight_external_impact:
                _append_agent_step(ctx, 
                    "news_agent",
                    {"query": ctx.query, "ticker": ticker},
                    why=f"{ticker} evidence contract: news agent synthesis.",
                    optional=True,
                    parallel_group=f"{group}_news_agents" if group else "news_agents",
                    task_ids=task_ids,
                )
        elif kind == "risk_profile":
            positions = [{"ticker": ticker, "weight": 1.0}]
            _append_tool_step(ctx, 
                "analyze_historical_drawdowns",
                {"ticker": ticker},
                why=f"{ticker} evidence contract: drawdown risk.",
                optional=True,
                parallel_group=group,
                task_ids=task_ids,
            )
            _append_tool_step(ctx, 
                "get_factor_exposure",
                {"positions": positions, "lookback_days": 252},
                why=f"{ticker} evidence contract: factor exposure.",
                optional=True,
                parallel_group=group,
                task_ids=task_ids,
            )
            if not lightweight_external_impact:
                _append_agent_step(ctx, 
                    "risk_agent",
                    {"query": ctx.query, "ticker": ticker},
                    why=f"{ticker} evidence contract: risk agent synthesis.",
                    optional=True,
                    parallel_group=f"{group}_risk_agents" if group else "risk_agents",
                    task_ids=task_ids,
                )
        elif kind == "filing_context":
            if ctx.market == "US":
                _append_tool_step(ctx, 
                    "get_sec_company_facts_quarterly",
                    {"ticker": ticker},
                    why=f"{ticker} evidence contract: quarterly company facts.",
                    optional=False,
                    parallel_group=group,
                    task_ids=task_ids,
                )
                _append_tool_step(ctx, 
                    "get_sec_filings",
                    {"ticker": ticker, "forms": ["10-K", "10-Q"], "limit": 4},
                    why=f"{ticker} evidence contract: SEC filings.",
                    optional=True,
                    parallel_group=group,
                    task_ids=task_ids,
                )
            else:
                _append_tool_step(ctx, 
                    "get_local_market_filings",
                    {"ticker": ticker, "limit": 5},
                    why=f"{ticker} evidence contract: local-market filings.",
                    optional=False,
                    parallel_group=group,
                    task_ids=task_ids,
                )
        elif kind == "transcript_context":
            _append_tool_step(ctx, 
                "get_earnings_call_transcripts",
                {"ticker": ticker, "limit": 5},
                why=f"{ticker} evidence contract: earnings call transcripts.",
                optional=True,
                parallel_group=group,
                task_ids=task_ids,
            )
        elif kind == "event_calendar":
            _append_tool_step(ctx, 
                "get_event_calendar",
                {"ticker": ticker},
                why=f"{ticker} evidence contract: event calendar.",
                optional=True,
                parallel_group=group,
                task_ids=task_ids,
            )
        elif kind == "options_derivatives":
            _append_tool_step(ctx, 
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
            _append_tool_step(ctx, 
                "get_insider_transactions",
                {"ticker": ticker, "days": 180, "limit": 50},
                why=f"{ticker} evidence contract: public insider transactions.",
                optional=True,
                parallel_group=group,
                task_ids=task_ids,
            )
            _append_tool_step(ctx, 
                "get_institution_holdings_by_ticker",
                {"ticker": ticker, "limit": 50},
                why=f"{ticker} evidence contract: institutional ownership holders.",
                optional=False,
                parallel_group=group,
                task_ids=task_ids,
            )
