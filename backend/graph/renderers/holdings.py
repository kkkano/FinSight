# -*- coding: utf-8 -*-
# 机械拆分自 backend/graph/nodes/chat_renderer.py（WP3 Task1，零行为变更）。
from __future__ import annotations

import json
import os
import re
import time
from typing import Any
from urllib.parse import quote_plus

from backend.graph.state import GraphState
from backend.graph.renderers.shared import (
    _finalize_chat_markdown,
    _intent_contract,
    _operation_names,
    _parse_jsonish,
    _step_outputs,
    _tickers,
)


def _request_requires_holdings(state: GraphState) -> bool:
    if "holdings" in _operation_names(state):
        return True
    contract = _intent_contract(state)
    required = contract.get("required_evidence")
    if isinstance(required, list) and "holdings_ownership" in {str(item) for item in required}:
        return True
    facets = contract.get("facets")
    if isinstance(facets, list) and "holdings" in {str(item) for item in facets}:
        return True
    frames: list[Any] = []
    frame = state.get("request_frame")
    if isinstance(frame, dict):
        frames.append(frame)
    raw_frames = state.get("request_frames")
    if isinstance(raw_frames, list):
        frames.extend(item for item in raw_frames if isinstance(item, dict))
    for item in frames:
        evidence = item.get("evidence_obligations")
        if isinstance(evidence, list) and "holdings_ownership" in {str(kind) for kind in evidence}:
            return True
    return False

def _format_compact_usd_thousands(value: Any) -> str:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return ""
    if amount >= 1_000_000:
        return f"${amount / 1_000_000:.2f}B"
    if amount >= 1_000:
        return f"${amount / 1_000:.1f}M"
    return f"${amount:.0f}K"

def _format_holdings_number(value: Any) -> str:
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:,.0f}" if value.is_integer() else f"{value:,.2f}"
    text = str(value or "").strip()
    return text

def _render_holdings_markdown(state: GraphState) -> str:
    target = ", ".join(_tickers(state)) or str(state.get("query") or "相关标的").strip() or "相关标的"
    lines: list[str] = [f"{target} 持仓/所有权证据："]
    added_detail = False
    notes: list[str] = []

    for step, output in _step_outputs(state):
        name = str(step.get("name") or "").strip()
        if name not in {
            "get_institutional_holdings",
            "get_institution_holdings_by_ticker",
            "get_insider_transactions",
            "get_holdings_overlap",
        }:
            continue
        payload = _parse_jsonish(output)
        if not isinstance(payload, dict):
            continue

        error = str(payload.get("error") or "").strip()
        message = str(payload.get("message") or "").strip()
        if error:
            label = name.replace("_", " ")
            notes.append(f"{label}: {message or error}")
            continue

        if name == "get_insider_transactions":
            transactions = [row for row in (payload.get("transactions") or []) if isinstance(row, dict)]
            ticker = str(payload.get("ticker") or "").strip().upper() or target
            if transactions:
                lines.append(f"- SEC Form 4 insider transactions for {ticker}:")
                for row in transactions[:5]:
                    date = str(row.get("transaction_date") or row.get("filing_date") or "").strip()
                    owner = str(row.get("owner_name") or row.get("reporting_owner_name") or "").strip()
                    code = str(row.get("transaction_code") or "?").strip()
                    side = str(row.get("acquired_disposed") or "").strip()
                    shares = _format_holdings_number(row.get("shares"))
                    price = _format_holdings_number(row.get("price_per_share"))
                    parts = [part for part in (date, owner, f"code {code}", side, f"{shares} shares" if shares else "", f"@ ${price}" if price else "") if part]
                    lines.append(f"  - {' | '.join(parts)}")
                added_detail = True
            else:
                lines.append(f"- SEC Form 4: no recent parsed insider transactions for {ticker} in this window.")
                added_detail = True
            note = (payload.get("regulatory_notes") or {}).get("form_4_due") if isinstance(payload.get("regulatory_notes"), dict) else ""
            if note:
                notes.append(str(note))

        elif name == "get_institution_holdings_by_ticker":
            ticker = str(payload.get("ticker") or "").strip().upper() or target
            holders = [row for row in (payload.get("holders") or []) if isinstance(row, dict)]
            if holders:
                lines.append(f"- Institutional holders for {ticker}:")
                for row in holders[:5]:
                    holder = str(row.get("holder_name") or row.get("name") or "").strip()
                    shares = _format_holdings_number(row.get("shares"))
                    value = _format_compact_usd_thousands(row.get("value_usd_thousands"))
                    parts = [part for part in (holder, f"{shares} shares" if shares else "", value) if part]
                    if parts:
                        lines.append(f"  - {' | '.join(parts)}")
                added_detail = True
            else:
                capability = str(payload.get("capability_note") or "").strip()
                lines.append(f"- Institutional holders for {ticker}: no by-ticker 13F holder rows were returned by this free SEC path.")
                if capability:
                    notes.append(capability)
                added_detail = True

        elif name == "get_institutional_holdings":
            holder = str(payload.get("holder_name") or payload.get("cik") or "institution").strip()
            quarter = str(payload.get("quarter") or "").strip()
            holdings = [row for row in (payload.get("holdings") or []) if isinstance(row, dict)]
            if holdings:
                suffix = f" ({quarter})" if quarter else ""
                lines.append(f"- {holder} 13F holdings{suffix}:")
                for row in holdings[:8]:
                    ticker = str(row.get("ticker") or "").strip().upper()
                    issuer = str(row.get("issuer_name") or "").strip()
                    shares = _format_holdings_number(row.get("shares"))
                    value = _format_compact_usd_thousands(row.get("value_usd_thousands"))
                    name_part = ticker or issuer
                    parts = [part for part in (name_part, issuer if ticker and issuer else "", f"{shares} shares" if shares else "", value) if part]
                    if parts:
                        lines.append(f"  - {' | '.join(parts)}")
                added_detail = True
            else:
                lines.append(f"- {holder} 13F: no recent matching holdings table was returned.")
                added_detail = True
            note = (payload.get("regulatory_notes") or {}).get("form_13f_due") if isinstance(payload.get("regulatory_notes"), dict) else ""
            if note:
                notes.append(str(note))

        elif name == "get_holdings_overlap":
            holder = str(payload.get("holder_name") or payload.get("cik") or "institution").strip()
            overlap = [str(item).strip().upper() for item in (payload.get("overlap_tickers") or []) if str(item).strip()]
            portfolio = [str(item).strip().upper() for item in (payload.get("portfolio_tickers") or []) if str(item).strip()]
            lines.append(f"- Holdings overlap with {holder}: {', '.join(overlap) if overlap else 'no overlap found'}")
            if portfolio:
                lines.append(f"  - Portfolio checked: {', '.join(portfolio)}")
            added_detail = True

    if not added_detail:
        lines.append("- 本轮识别为持仓/内部人/13F 查询，但没有拿到可用的 SEC holdings 工具输出；我不会改用价格数据来冒充持仓答案。")

    if notes:
        lines.append("")
        lines.append("说明：")
        for note in list(dict.fromkeys(notes))[:4]:
            lines.append(f"- {note}")

    return _finalize_chat_markdown(lines, state)


def render_holdings(state: GraphState, ctx: dict[str, Any]) -> str | None:
    """原分支#8：持仓明细请求。"""
    if _request_requires_holdings(state):
        return _render_holdings_markdown(state)
    return None
