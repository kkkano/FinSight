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
from backend.graph.understanding_v2 import VALUATION_COMPARE_LIGHT_PROFILE


FORBIDDEN_CHAT_MARKERS = (
    "本轮问题包含",
    "分析对象",
    "get_stock_price",
    "get_company_news",
    "get_company_info",
    "Suggested ladder",
    "output（）",
    "暂无技术指标",
    "问题：",
    "后续关注：",
)

def _parse_jsonish(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return value
    if not (text.startswith("{") or text.startswith("[")):
        return value
    try:
        return json.loads(text)
    except Exception:
        return value

def _tasks(state: GraphState) -> list[dict[str, Any]]:
    raw = state.get("tasks")
    return [item for item in (raw if isinstance(raw, list) else []) if isinstance(item, dict)]

def _operation_names(state: GraphState) -> set[str]:
    names: set[str] = set()
    op = state.get("operation")
    if isinstance(op, dict) and isinstance(op.get("name"), str):
        names.add(op["name"])
    for task in _tasks(state):
        task_op = task.get("operation")
        if isinstance(task_op, dict) and isinstance(task_op.get("name"), str):
            names.add(task_op["name"])
    return names

def _tickers(state: GraphState) -> list[str]:
    seen: set[str] = set()
    values: list[str] = []
    subject = state.get("subject") if isinstance(state.get("subject"), dict) else {}
    for raw in subject.get("tickers") or []:
        ticker = str(raw or "").strip().upper()
        if ticker and ticker not in seen:
            seen.add(ticker)
            values.append(ticker)
    for task in _tasks(state):
        for raw in task.get("tickers") or []:
            ticker = str(raw or "").strip().upper()
            if ticker and ticker not in seen:
                seen.add(ticker)
                values.append(ticker)
    return values

def _step_outputs(state: GraphState) -> list[tuple[dict[str, Any], Any]]:
    artifacts = state.get("artifacts") if isinstance(state.get("artifacts"), dict) else {}
    step_results = artifacts.get("step_results") if isinstance(artifacts.get("step_results"), dict) else {}
    plan_ir = state.get("plan_ir") if isinstance(state.get("plan_ir"), dict) else {}
    steps = plan_ir.get("steps") if isinstance(plan_ir.get("steps"), list) else []
    step_index = {str(step.get("id")): step for step in steps if isinstance(step, dict) and step.get("id")}

    outputs: list[tuple[dict[str, Any], Any]] = []
    for step_id, result in step_results.items():
        if not isinstance(result, dict):
            continue
        output = result.get("output")
        if isinstance(output, dict) and output.get("skipped"):
            continue
        outputs.append((step_index.get(str(step_id), {}), _parse_jsonish(output)))
    return outputs

def _first_matching_output(state: GraphState, names: set[str]) -> Any:
    for step, output in _step_outputs(state):
        if str(step.get("name") or "") in names:
            return output
    return None

def _format_number(value: Any, digits: int = 2) -> str:
    if isinstance(value, (int, float)):
        return f"{value:.{digits}f}"
    text = str(value or "").strip()
    return text

def _is_citable_url(url: str) -> bool:
    text = str(url or "").strip()
    if not text.startswith(("http://", "https://")):
        return False
    lowered = text.lower()
    non_article_markers = (
        "google.com/search",
        "finance.yahoo.com/search",
        "finance.yahoo.com/quote/",
        "benzinga.com/search",
        "reuters.com/site-search",
        "cnbc.com/search",
        "marketwatch.com/search",
    )
    return not any(marker in lowered for marker in non_article_markers)

def _append_sources(lines: list[str], sources: list[dict[str, str]]) -> None:
    usable = [item for item in sources if _is_citable_url(str(item.get("url") or ""))]
    if not usable:
        return
    lines.extend(["", "来源："])
    for item in usable[:5]:
        meta = " / ".join(part for part in (item.get("source"), item.get("published")) if part)
        suffix = f"（{meta}）" if meta else ""
        lines.append(f"- [{item['title']}]({item['url']}){suffix}")


def _append_sources_for_state(
    lines: list[str], sources: list[dict[str, str]], state: GraphState
) -> None:
    artifacts = state.get("artifacts") if isinstance(state.get("artifacts"), dict) else {}
    if artifacts.get("render_group_body"):
        return
    _append_sources(lines, sources)

def _task_index(state: GraphState) -> dict[str, dict[str, Any]]:
    return {str(task.get("id")): task for task in _tasks(state) if task.get("id")}

def _blocked_tasks(state: GraphState) -> list[dict[str, Any]]:
    raw = state.get("blocked_tasks")
    return [item for item in (raw if isinstance(raw, list) else []) if isinstance(item, dict)]

def _append_blocked_notes(lines: list[str], state: GraphState) -> None:
    blocked = _blocked_tasks(state)
    if not blocked:
        return
    notes: list[str] = []
    for item in blocked[:3]:
        question = str(item.get("question") or "").strip()
        reason = str(item.get("reason") or "").strip()
        if reason == "missing_portfolio_holdings":
            text = question or "要判断对你持仓的影响，还需要持仓列表、权重，或你允许我按一个假设组合估算。"
        elif question:
            text = question
        else:
            text = "这部分还缺少必要上下文，所以我先没有硬给结论。"
        if text and text not in notes:
            notes.append(text)
    if not notes:
        return
    if lines and lines[-1] != "":
        lines.append("")
    lines.append("另外还有一部分需要你补充后才能判断：")
    lines.extend(f"- {note}" for note in notes)

def _ticker_for_step(step: dict[str, Any], output: Any, state: GraphState) -> str:
    inputs = step.get("inputs") if isinstance(step.get("inputs"), dict) else {}
    ticker = str(inputs.get("ticker") or "").strip().upper()
    if ticker:
        return ticker
    parsed = _parse_jsonish(output)
    if isinstance(parsed, dict):
        ticker = str(parsed.get("ticker") or parsed.get("symbol") or "").strip().upper()
        if ticker:
            return ticker
    task_index = _task_index(state)
    for task_id in step.get("task_ids") or []:
        task = task_index.get(str(task_id))
        tickers = task.get("tickers") if isinstance(task, dict) else None
        if isinstance(tickers, list) and tickers:
            ticker = str(tickers[0] or "").strip().upper()
            if ticker:
                return ticker
        subject_label = str((task or {}).get("subject_label") or "").strip()
        if subject_label:
            return subject_label
    tickers = _tickers(state)
    return tickers[0] if len(tickers) == 1 else ""

def _subject_types(state: GraphState) -> set[str]:
    values: set[str] = set()
    subject = state.get("subject") if isinstance(state.get("subject"), dict) else {}
    subject_type = str(subject.get("subject_type") or "").strip().lower()
    if subject_type:
        values.add(subject_type)
    for task in _tasks(state):
        task_type = str(task.get("subject_type") or "").strip().lower()
        if task_type:
            values.add(task_type)
    return values

def _risk_or_qa_fallback_lines(state: GraphState, risks: str = "") -> list[str]:
    risk_points: list[str] = []
    for line in str(risks or "").splitlines():
        text = line.strip(" -•\t")
        if not text:
            continue
        if any(marker in text for marker in ("仅供参考", "不构成投资建议", "免责声明")):
            continue
        risk_points.append(text)
    if risk_points:
        return risk_points[:5]

    return ["这轮没有足够的可靠证据支撑风险判断，我先不硬编风险点。"]

def _case_insensitive_get(row: dict[str, Any], key: str) -> Any:
    if key in row:
        return row.get(key)
    wanted = key.lower()
    for raw_key, value in row.items():
        if str(raw_key).lower() == wanted:
            return value
    return None

def _company_identity_tokens(state: GraphState) -> set[str]:
    tokens = {ticker.lower() for ticker in _tickers(state) if ticker}
    generic = {"corp", "corporation", "inc", "ltd", "limited", "company", "class", "ordinary", "shares"}

    company_info = _parse_jsonish(_first_matching_output(state, {"get_company_info"}))
    candidates: list[str] = []
    if isinstance(company_info, dict):
        candidates.extend(
            str(company_info.get(key) or "")
            for key in ("name", "company_name", "longName", "shortName")
        )
    elif isinstance(company_info, str):
        match = re.search(r"(?:^|\n)\s*-\s*Name:\s*([^\n]+)", company_info, re.IGNORECASE)
        if match:
            candidates.append(match.group(1))

    for candidate in candidates:
        for word in re.findall(r"[A-Za-z][A-Za-z0-9&.-]{2,}", candidate):
            normalized = word.strip(" .,-").lower()
            if len(normalized) >= 3 and normalized not in generic:
                tokens.add(normalized)
    return tokens

def _append_render_var_block(lines: list[str], text: str) -> None:
    cleaned = str(text or "").strip()
    if not cleaned:
        return
    if lines and lines[-1] != "":
        lines.append("")
    lines.append(cleaned)

def _sanitize_chat_markdown(text: str) -> str:
    cleaned = str(text or "").strip()
    cleaned = re.sub(r"\s*\|\s*Suggested ladder\s*:\s*[^\n]+", "", cleaned, flags=re.IGNORECASE)
    for marker in FORBIDDEN_CHAT_MARKERS:
        cleaned = cleaned.replace(marker, "")
    cleaned = re.sub(r"(?m)^\s*\*{2,}\s*$\n?", "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip() + "\n"

def _finalize_chat_markdown(lines: list[str], state: GraphState) -> str:
    artifacts = state.get("artifacts") if isinstance(state.get("artifacts"), dict) else {}
    if artifacts.get("render_group_body"):
        return _sanitize_chat_markdown("\n".join(lines))
    _append_blocked_notes(lines, state)
    return _sanitize_chat_markdown("\n".join(lines))

def _intent_contract(state: GraphState) -> dict[str, Any]:
    contract = state.get("intent_contract")
    if isinstance(contract, dict):
        return contract
    understanding = state.get("understanding")
    if isinstance(understanding, dict):
        contract = understanding.get("intent_contract")
        if isinstance(contract, dict):
            return contract
    trace = state.get("trace")
    if isinstance(trace, dict):
        contract = trace.get("intent_contract")
        if isinstance(contract, dict):
            return contract
        contracts = trace.get("intent_contracts")
        if isinstance(contracts, list):
            for item in contracts:
                if isinstance(item, dict):
                    return item
    contracts = state.get("intent_contracts")
    if isinstance(contracts, list):
        for item in contracts:
            if isinstance(item, dict):
                return item
    frame = state.get("request_frame")
    if isinstance(frame, dict):
        frame_contract = frame.get("intent_contract")
        if isinstance(frame_contract, dict):
            return frame_contract
        render_contract = frame.get("render_contract")
        if isinstance(render_contract, dict):
            subject = frame.get("subject") if isinstance(frame.get("subject"), dict) else {}
            tickers = subject.get("tickers") if isinstance(subject.get("tickers"), list) else []
            evidence = frame.get("evidence_obligations") if isinstance(frame.get("evidence_obligations"), list) else []
            return {
                "render_intent": dict(render_contract),
                "primary_tickers": [str(ticker).strip().upper() for ticker in tickers if str(ticker).strip()],
                "per_ticker_required": bool(evidence),
                "required_evidence": list(evidence),
            }
    frames = state.get("request_frames")
    if isinstance(frames, list):
        for frame in frames:
            if not isinstance(frame, dict):
                continue
            frame_contract = frame.get("intent_contract")
            if isinstance(frame_contract, dict):
                return frame_contract
            render_contract = frame.get("render_contract")
            if isinstance(render_contract, dict):
                subject = frame.get("subject") if isinstance(frame.get("subject"), dict) else {}
                tickers = subject.get("tickers") if isinstance(subject.get("tickers"), list) else []
                evidence = frame.get("evidence_obligations") if isinstance(frame.get("evidence_obligations"), list) else []
                return {
                    "render_intent": dict(render_contract),
                    "primary_tickers": [str(ticker).strip().upper() for ticker in tickers if str(ticker).strip()],
                    "per_ticker_required": bool(evidence),
                    "required_evidence": list(evidence),
                }
    return {}

def _has_contract_facet(state: GraphState, facet: str) -> bool:
    facets = _intent_contract(state).get("facets")
    return isinstance(facets, list) and facet in {str(item) for item in facets}

def _understanding_v2(state: GraphState) -> dict[str, Any]:
    payload = state.get("understanding_v2")
    if isinstance(payload, dict):
        return payload
    understanding = state.get("understanding") if isinstance(state.get("understanding"), dict) else {}
    payload = understanding.get("v2") if isinstance(understanding, dict) else {}
    return payload if isinstance(payload, dict) else {}

def _v2_profiles(state: GraphState) -> set[str]:
    profiles: set[str] = set()
    for requirement in (_understanding_v2(state).get("evidence_requirements") or []):
        if not isinstance(requirement, dict):
            continue
        profile = str(requirement.get("profile") or "").strip()
        if profile:
            profiles.add(profile)
    for task in _tasks(state):
        operation = task.get("operation") if isinstance(task.get("operation"), dict) else {}
        params = operation.get("params") if isinstance(operation.get("params"), dict) else {}
        for key in ("evidence_profile", "comparison_data_profile", "budget_profile"):
            profile = str(params.get(key) or "").strip()
            if profile:
                profiles.add(profile)
        if str(params.get("evidence_focus") or "").strip().lower() == "valuation":
            profiles.add(VALUATION_COMPARE_LIGHT_PROFILE)
    return profiles
