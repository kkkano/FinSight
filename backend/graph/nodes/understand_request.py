# -*- coding: utf-8 -*-
"""请求理解节点：一次性完成闲聊、标的、任务和阻塞项识别。"""
from __future__ import annotations

import re
from typing import Any

from backend.config.ticker_mapping import dedup_tickers, extract_tickers, normalize_ticker
from backend.graph.event_bus import emit_event
from backend.graph.nodes.decide_output_mode import decide_output_mode
from backend.graph.nodes.parse_operation import parse_operation
from backend.graph.nodes.query_intent import has_financial_intent, is_casual_chat, is_greeting
from backend.graph.state import GraphState


_INDEX_TICKERS = {"SPY", "QQQ", "DIA", "IWM", "VTI", "^IXIC", "^DJI", "^GSPC", "^RUT", "^VIX"}
_NON_ASSET_TOKENS = {"PDF", "DOC", "DOCX", "PPT", "PPTX", "CSV", "TXT", "HTML"}
_NEWS_HINTS = ("新闻", "消息", "大新闻", "发生什么", "快讯", "news", "headline", "latest")
_PRICE_HINTS = ("股价", "涨了多少", "跌了多少", "涨幅", "跌幅", "表现", "行情", "price", "quote", "performance")
_IMPACT_HINTS = ("影响", "冲击", "拖累", "风险", "利好", "利空", "impact", "affect", "risk")
_TECHNICAL_HINTS = ("技术面", "技术分析", "k线", "均线", "macd", "rsi", "technical")
_COMPARE_HINTS = ("对比", "比较", "相比", "vs", "versus", "谁更强", "哪个好", "哪个", "compare")
_ALERT_HINTS = ("提醒", "预警", "到达", "触及", "涨到", "跌到", "跌破", "突破", "低于", "高于", "alert", "notify", "remind me")
_PORTFOLIO_HINTS = ("持仓", "组合", "仓位", "调仓", "portfolio", "holdings", "rebalance")
_MACRO_HINTS = (
    "美联储", "联储", "降息", "加息", "利率", "fomc", "fed", "cpi", "ppi", "通胀",
    "国债", "收益率", "宏观", "大盘", "纳指", "公告", "大型科技股", "科技股估值", "market",
)
_THEME_HINTS = ("半导体", "芯片", "ai", "人工智能", "大型科技股", "科技股")
_FALLBACK_HINTS = ("如果不知道", "不知道就", "没持仓就", "没有持仓就", "按等权", "按大型科技股", "fallback")
# P2 (2026-05-03) — vague subject deixis: when the user says "this stock"
# without naming it AND ui_context.active_symbol is present, do a transparent
# weak fallback (bind active_symbol + warn user it can be corrected).
# Risk: a wrong fallback is corrected by one user message; a missed fallback
# costs an extra clarify round-trip. We bias toward the cheaper failure mode.
_VAGUE_SUBJECT_HINTS = (
    "这只票", "这个票", "那只票", "这只股", "这个股", "那只股",
    "这家公司", "那家公司", "这家", "那家",
    "这只", "这个", "这支",
    "刚才那个", "刚才说的", "之前那个",
    "this stock", "that stock", "this one", "the company",
)
_SOCIAL_PREFIX_RE = re.compile(r"^\s*(你好|您好|早|早上好|嗨|哈喽|hello|hi)[，,。\s]*(今天天气不错[，,。\s]*)?", re.IGNORECASE)


def _contains_any(text: str, hints: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(h.lower() in lowered for h in hints)


def _subject_type_for_ticker(ticker: str) -> str:
    symbol = str(ticker or "").strip().upper()
    if not symbol:
        return "unknown"
    if symbol.endswith("=F"):
        return "commodity"
    if symbol.startswith("^") or symbol in _INDEX_TICKERS:
        return "index"
    return "company"


def _selection_subject_type(selection_types: list[str]) -> str:
    if not selection_types:
        return "research_doc"
    if len(selection_types) == 1:
        first = selection_types[0]
        if first == "news":
            return "news_item"
        if first == "filing":
            return "filing"
        return "research_doc"
    if all(t == "news" for t in selection_types):
        return "news_set"
    if all(t == "filing" for t in selection_types):
        return "filing"
    return "research_doc"


def _time_scope(query: str) -> dict[str, Any]:
    q = query.lower()
    if "昨天" in q or "yesterday" in q:
        return {"kind": "yesterday", "label": "昨天"}
    if "今天" in q or "今日" in q or "today" in q:
        return {"kind": "today", "label": "今天"}
    if "这周" in q or "本周" in q or "this week" in q:
        return {"kind": "this_week", "label": "本周"}
    if "最近" in q or "recent" in q:
        return {"kind": "recent", "label": "最近"}
    if "最新" in q or "latest" in q:
        return {"kind": "latest", "label": "最新"}
    return {"kind": "unspecified", "label": ""}


def _operation(name: str, confidence: float = 0.75, params: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"name": name, "confidence": confidence, "params": params or {}}


def _company_operations(query: str, *, tickers: list[str]) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []
    if len(tickers) >= 2 and _contains_any(query, _COMPARE_HINTS):
        operations.append(_operation("compare", 0.86))
        return operations
    if _contains_any(query, _PRICE_HINTS):
        operations.append(_operation("price", 0.82))
    if _contains_any(query, _NEWS_HINTS):
        operations.append(_operation("fetch", 0.78, {"topic": "news"}))
    if _contains_any(query, _IMPACT_HINTS):
        operations.append(_operation("analyze_impact", 0.78))
    if _contains_any(query, _TECHNICAL_HINTS):
        operations.append(_operation("technical", 0.82))
    if _contains_any(query, _ALERT_HINTS):
        operations.append(_operation("alert_set", 0.88))
    if operations:
        return operations

    subject = {"subject_type": "company", "tickers": tickers}
    parsed = parse_operation({"query": query, "subject": subject})
    return [parsed.get("operation") or _operation("qa", 0.45)]


def _macro_operation(query: str) -> dict[str, Any]:
    if any(h in query for h in ("降息没", "有没有降息", "概率", "变了吗", "事实", "核查")):
        return _operation("fact_check", 0.76)
    if _contains_any(query, _IMPACT_HINTS) or "估值" in query:
        return _operation("analyze_impact", 0.78)
    if _contains_any(query, _NEWS_HINTS):
        return _operation("fetch", 0.72, {"topic": "macro_news"})
    return _operation("macro_brief", 0.68)


def _macro_subject_label(query: str) -> str:
    q = str(query or "").lower()
    indicators = [
        ("cpi", "CPI"),
        ("ppi", "PPI"),
        ("fomc", "FOMC"),
        ("fed", "美联储"),
        ("美联储", "美联储"),
        ("联储", "美联储"),
        ("降息", "利率路径"),
        ("加息", "利率路径"),
        ("利率", "利率路径"),
        ("通胀", "通胀"),
        ("收益率", "国债收益率"),
        ("国债", "国债收益率"),
        ("纳指", "纳指"),
        ("大型科技股", "大型科技股"),
        ("科技股", "科技股"),
    ]
    labels: list[str] = []
    for token, label in indicators:
        if token in q and label not in labels:
            labels.append(label)
    return " / ".join(labels[:3]) if labels else "宏观环境"


def _social_prefix(query: str) -> str:
    match = _SOCIAL_PREFIX_RE.match(query or "")
    return match.group(0).strip(" ，,。") if match else ""


def _direct_reply(query: str) -> str:
    if is_greeting(query):
        return "你好！你可以直接告诉我股票、公司、宏观主题或持仓问题，我会先识别任务再开始分析。"
    return "我主要负责金融投研问题。你可以输入股票代码、公司名称、宏观主题，或让我比较多只股票。"


def _normalize_selection(ui_context: dict[str, Any]) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    raw = ui_context.get("selections")
    if not raw and isinstance(ui_context.get("selection"), dict):
        raw = [ui_context["selection"]]
    selections = raw if isinstance(raw, list) else []
    payload = [item for item in selections if isinstance(item, dict)]
    ids: list[str] = []
    types: list[str] = []
    seen_ids: set[str] = set()
    for item in payload:
        item_id = str(item.get("id") or "").strip()
        item_type = str(item.get("type") or "").strip().lower()
        if item_type == "report":
            item_type = "doc"
        if item_id and item_id not in seen_ids:
            seen_ids.add(item_id)
            ids.append(item_id)
        if item_type:
            types.append(item_type)
    return ids, types, payload


def _portfolio_context_available(query: str, ui_context: dict[str, Any]) -> bool:
    if "我持有" in query or "持有" in query and bool(extract_tickers(query).get("tickers")):
        return True
    for key in ("portfolio", "positions", "holdings"):
        value = ui_context.get(key)
        if isinstance(value, (list, tuple, dict)) and len(value) > 0:
            return True
    return False


def _add_task(
    tasks: list[dict[str, Any]],
    *,
    subject_type: str,
    operation: dict[str, Any],
    query: str,
    tickers: list[str] | None = None,
    subject_label: str = "",
    selection_ids: list[str] | None = None,
    selection_types: list[str] | None = None,
    priority: int = 50,
    reason: str = "rule_match",
    constraints: list[str] | None = None,
    params: dict[str, Any] | None = None,
) -> None:
    task_id = f"task_{len(tasks) + 1}"
    tasks.append(
        {
            "id": task_id,
            "subject_type": subject_type,
            "subject_label": subject_label,
            "tickers": tickers or [],
            "selection_ids": selection_ids or [],
            "selection_types": selection_types or [],
            "operation": operation,
            "time_scope": _time_scope(query),
            "priority": priority,
            "status": "ready",
            "reason": reason,
            "constraints": constraints or [],
            "params": params or {},
        }
    )


def _build_subject(primary: dict[str, Any] | None, selection_payload: list[dict[str, Any]]) -> dict[str, Any]:
    if not primary:
        return {
            "subject_type": "unknown",
            "tickers": [],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
            "binding_tier": "understanding_none",
        }
    return {
        "subject_type": primary.get("subject_type") or "unknown",
        "tickers": list(primary.get("tickers") or []),
        "selection_ids": list(primary.get("selection_ids") or []),
        "selection_types": list(primary.get("selection_types") or []),
        "selection_payload": selection_payload if primary.get("selection_ids") else [],
        "binding_tier": "understanding",
        "is_comparison": (primary.get("operation") or {}).get("name") == "compare",
    }


async def _emit_understanding_trace(understanding: dict[str, Any]) -> None:
    await emit_event(
        {
            "type": "trace",
            "visibility": "user",
            "stage": "understanding",
            "status": "done",
            "title": "已理解请求",
            "summary": understanding.get("user_visible_summary") or "",
            "tasks": [
                {
                    "id": task.get("id"),
                    "subject_type": task.get("subject_type"),
                    "tickers": task.get("tickers") or [],
                    "operation": (task.get("operation") or {}).get("name"),
                    "time_scope": (task.get("time_scope") or {}).get("kind"),
                }
                for task in (understanding.get("tasks") or [])[:8]
            ],
            "blocked_tasks": [
                {"id": task.get("id"), "reason": task.get("reason")}
                for task in (understanding.get("blocked_tasks") or [])[:4]
            ],
        }
    )


async def understand_request(state: GraphState) -> dict[str, Any]:
    query = (state.get("query") or "").strip()
    ui_context = state.get("ui_context") if isinstance(state.get("ui_context"), dict) else {}
    output_mode = (decide_output_mode(state).get("output_mode") or "brief")

    tasks: list[dict[str, Any]] = []
    blocked_tasks: list[dict[str, Any]] = []
    context_refs: list[dict[str, Any]] = []
    fallback_assumptions: list[str] = []
    artifacts = dict(state.get("artifacts") or {})
    trace = dict(state.get("trace") or {})

    selection_ids, selection_types, selection_payload = _normalize_selection(ui_context)
    social_prefix = _social_prefix(query)
    ticker_meta = extract_tickers(query)
    tickers = dedup_tickers(
        [str(t) for t in (ticker_meta.get("tickers") or []) if str(t).strip().upper() not in _NON_ASSET_TOKENS]
    )
    if not tickers and isinstance(ui_context.get("active_symbol"), str) and has_financial_intent(query):
        tickers = [normalize_ticker(str(ui_context["active_symbol"]))]
        context_refs.append({"source": "ui_context", "key": "active_symbol", "label": "当前标的", "value": tickers[0]})

    # P2 weak fallback — query lacks tickers AND lacks financial intent, but
    # contains a vague subject deixis ("这只票", "this stock", ...) and
    # ui_context.active_symbol is present. Bind the active symbol and surface
    # the assumption to the user so they can correct it in one turn.
    if (
        not tickers
        and isinstance(ui_context.get("active_symbol"), str)
        and ui_context["active_symbol"].strip()
        and _contains_any(query, _VAGUE_SUBJECT_HINTS)
    ):
        active = normalize_ticker(str(ui_context["active_symbol"]))
        if active:
            tickers = [active]
            context_refs.append(
                {
                    "source": "ui_context",
                    "key": "active_symbol",
                    "label": "当前标的(弱兜底)",
                    "value": active,
                }
            )
            fallback_assumptions.append(
                f"按你正在看的 {active} 处理，如不是请告诉我具体哪只。"
            )

    if not query:
        blocked_tasks.append(
            {
                "id": "blocked_1",
                "subject_type": "unknown",
                "subject_label": "",
                "operation": _operation("qa", 0.0),
                "reason": "empty_query",
                "question": "请先输入你的问题。",
                "suggestions": ["输入股票代码、公司名称、宏观主题，或选择新闻/财报后提问"],
                "fallback_allowed": False,
            }
        )
    elif is_casual_chat(query) and not tickers and not _contains_any(query, _MACRO_HINTS) and not selection_ids:
        artifacts["draft_markdown"] = _direct_reply(query)
        understanding = {
            "route": "direct",
            "original_query": query,
            "cleaned_query": query,
            "language": "zh" if re.search(r"[\u4e00-\u9fff]", query) else "en",
            "social_prefix": query,
            "user_visible_summary": "识别为普通对话，不进入投研流水线。",
            "confidence": 0.86,
            "tasks": [],
            "blocked_tasks": [],
            "context_refs": context_refs,
            "fallback_assumptions": [],
        }
        trace["understanding"] = understanding
        await _emit_understanding_trace(understanding)
        return {
            "understanding": understanding,
            "tasks": [],
            "blocked_tasks": [],
            "context_refs": context_refs,
            "subject": _build_subject(None, []),
            "operation": _operation("chat", 0.86),
            "clarify": {"needed": False, "reason": "", "question": "", "suggestions": []},
            "chat_responded": True,
            "artifacts": artifacts,
            "trace": trace,
        }

    if selection_ids:
        subject_type = _selection_subject_type(selection_types)
        parsed = parse_operation(
            {
                "query": query,
                "subject": {
                    "subject_type": subject_type,
                    "tickers": tickers,
                    "selection_ids": selection_ids,
                    "selection_types": selection_types,
                },
            }
        )
        _add_task(
            tasks,
            subject_type=subject_type,
            operation=parsed.get("operation") or _operation("summarize", 0.65),
            query=query,
            tickers=tickers,
            selection_ids=selection_ids,
            selection_types=selection_types,
            priority=10,
            reason="ui_selection",
        )

    if tickers:
        if len(tickers) >= 2 and _contains_any(query, _COMPARE_HINTS):
            _add_task(
                tasks,
                subject_type="company",
                operation=_operation("compare", 0.86),
                query=query,
                tickers=tickers,
                priority=20,
                reason="multi_ticker_compare",
            )
            extra_operations: list[dict[str, Any]] = []
            if _contains_any(query, _PRICE_HINTS):
                extra_operations.append(_operation("price", 0.82))
            if _contains_any(query, _NEWS_HINTS):
                extra_operations.append(_operation("fetch", 0.78, {"topic": "news"}))
            if _contains_any(query, _IMPACT_HINTS) and not re.search(r"(哪个|谁).{0,8}(风险|risk)", query, re.IGNORECASE):
                extra_operations.append(_operation("analyze_impact", 0.78))
            for ticker in tickers:
                subject_type = _subject_type_for_ticker(ticker)
                for operation in extra_operations:
                    _add_task(
                        tasks,
                        subject_type=subject_type,
                        operation=operation,
                        query=query,
                        tickers=[ticker],
                        subject_label=ticker,
                        priority=26,
                        reason="compare_subtask",
                    )
        else:
            for ticker in tickers:
                subject_type = _subject_type_for_ticker(ticker)
                for operation in _company_operations(query, tickers=tickers):
                    _add_task(
                        tasks,
                        subject_type=subject_type,
                        operation=operation,
                        query=query,
                        tickers=[ticker],
                        subject_label=ticker,
                        priority=25,
                        reason="ticker_or_alias",
                    )

    has_macro = _contains_any(query, _MACRO_HINTS)
    if has_macro:
        _add_task(
            tasks,
            subject_type="macro",
            subject_label=_macro_subject_label(query),
            operation=_macro_operation(query),
            query=query,
            priority=30,
            reason="macro_hint",
        )

    if _contains_any(query, _THEME_HINTS) and not has_macro:
        if not any(task.get("subject_type") == "theme" for task in tasks):
            _add_task(
                tasks,
                subject_type="theme",
                subject_label="主题/行业",
                operation=_operation("news_impact" if _contains_any(query, _IMPACT_HINTS) else "fetch", 0.7),
                query=query,
                priority=35,
                reason="theme_hint",
            )

    has_portfolio = _contains_any(query, _PORTFOLIO_HINTS)
    if has_portfolio:
        if _portfolio_context_available(query, ui_context):
            _add_task(
                tasks,
                subject_type="portfolio",
                subject_label="当前持仓",
                operation=_operation("rebalance_check" if "调仓" in query else "portfolio_impact", 0.74),
                query=query,
                tickers=tickers,
                priority=40,
                reason="portfolio_context_available",
            )
        elif _contains_any(query, _FALLBACK_HINTS):
            fallback_assumptions.append("用户允许在缺少持仓明细时使用查询中的替代假设。")
            _add_task(
                tasks,
                subject_type="portfolio",
                subject_label="持仓替代假设",
                operation=_operation("portfolio_fallback", 0.58),
                query=query,
                tickers=tickers,
                priority=80,
                reason="user_allowed_fallback",
                params={"fallback": True},
            )
        else:
            blocked_tasks.append(
                {
                    "id": f"blocked_{len(blocked_tasks) + 1}",
                    "subject_type": "portfolio",
                    "subject_label": "我的持仓",
                    "operation": _operation("portfolio_impact", 0.0),
                    "reason": "missing_portfolio_holdings",
                    "question": "要判断持仓影响或调仓，需要你的持仓列表、权重或允许我按假设组合估算。",
                    "suggestions": ["补充持仓和大致权重", "或说明按等权科技股组合估算"],
                    "fallback_allowed": True,
                }
            )

    if not tasks and blocked_tasks:
        route = "clarify"
    elif tasks and all((task.get("operation") or {}).get("name") == "alert_set" for task in tasks):
        route = "alert"
    elif tasks:
        route = "research"
    else:
        route = "clarify"
        blocked_tasks.append(
            {
                "id": "blocked_1",
                "subject_type": "unknown",
                "subject_label": "",
                "operation": _operation("qa", 0.0),
                "reason": "missing_analysis_target",
                "question": "我需要知道你想分析的公司、股票、宏观主题、新闻、财报或持仓。",
                "suggestions": ["输入公司名或 ticker，例如 谷歌 / GOOGL", "输入宏观主题，例如 美联储利率路径"],
                "fallback_allowed": False,
            }
        )

    if route == "clarify":
        first_blocked = blocked_tasks[0] if blocked_tasks else {}
        suggestions = list(first_blocked.get("suggestions") or [])
        question = str(first_blocked.get("question") or "请补充分析对象。")
        artifacts["draft_markdown"] = "\n".join([question, "", "你可以这样做：", *[f"- {s}" for s in suggestions]]).strip()

    if "30秒" in query or "先别做长报告" in query or "不要长篇" in query or "快速" in query:
        output_mode = "brief"

    primary = tasks[0] if tasks else None
    operation = (primary or {}).get("operation") or _operation("qa", 0.0)
    subject = _build_subject(primary, selection_payload)
    clarify = {
        "needed": route == "clarify",
        "reason": str((blocked_tasks[0] if blocked_tasks else {}).get("reason") or ""),
        "question": str((blocked_tasks[0] if blocked_tasks else {}).get("question") or ""),
        "suggestions": list((blocked_tasks[0] if blocked_tasks else {}).get("suggestions") or []),
    }
    summary_bits = []
    if tasks:
        for task in tasks[:5]:
            op_name = (task.get("operation") or {}).get("name")
            subject_label = task.get("subject_label") or ",".join(task.get("tickers") or []) or task.get("subject_type")
            summary_bits.append(f"{subject_label}:{op_name}")
    if blocked_tasks:
        summary_bits.append(f"阻塞项:{len(blocked_tasks)}")
    user_visible_summary = "；".join(summary_bits) if summary_bits else "需要补充信息。"

    understanding = {
        "route": route,
        "original_query": query,
        "cleaned_query": query,
        "language": "zh" if re.search(r"[\u4e00-\u9fff]", query) else "en",
        "social_prefix": social_prefix,
        "user_visible_summary": user_visible_summary,
        "confidence": 0.78 if tasks else 0.42,
        "tasks": tasks,
        "blocked_tasks": blocked_tasks,
        "context_refs": context_refs,
        "fallback_assumptions": fallback_assumptions,
    }
    trace["understanding"] = understanding
    await _emit_understanding_trace(understanding)

    return {
        "understanding": understanding,
        "tasks": tasks,
        "blocked_tasks": blocked_tasks,
        "context_refs": context_refs,
        "subject": subject,
        "operation": operation,
        "output_mode": output_mode,
        "clarify": clarify,
        "chat_responded": route == "direct",
        "artifacts": artifacts,
        "trace": trace,
    }


__all__ = ["understand_request"]
