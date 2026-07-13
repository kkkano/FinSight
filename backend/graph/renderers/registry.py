# -*- coding: utf-8 -*-
"""chat_renderer 注册表入口（WP3 Task1 机械拆分，零行为变更）。

原 render_chat_markdown 是互斥早退分支链：每个分支渲染完整回复并 return。
注册表语义因此为 **first-non-None-wins**：按原分支顺序逐个调用 renderer，
第一个返回非 None 的结果即最终 markdown（末位 render_default 恒返回）。

ctx 分两阶段构建，保持与原函数头完全一致的计算顺序与副作用时点：
phase1（build_render_ctx）→ renderer#1（last_report 跟聊）→
phase2（enrich_render_ctx，含 news_map 联网 fallback 增补）→ 其余 renderer。
"""
from __future__ import annotations

from typing import Any, Callable

from backend.graph.memory_scope import current_report_context
from backend.graph.state import GraphState

from backend.graph.renderers.shared import (
    _finalize_chat_markdown,
    _operation_names,
    _tickers,
)
from backend.graph.renderers.synthesis_vars import _render_vars, _useful_render_var
from backend.graph.renderers.news import (
    _evidence_items,
    _news_by_ticker,
    _news_map_has_citable_url,
    _reply_contract_requires_links,
    _requested_news_link_count,
)
from backend.graph.renderers.news_items import _dedupe_news_items
from backend.graph.renderers.news_fallback import (
    _direct_news_article_fallback_map,
    _news_article_fallback_allowed,
)
from backend.graph.renderers.price import _prices_by_ticker
from backend.graph.renderers.url_fetch import _has_url_context, render_url_context
from backend.graph.renderers.misc import (
    _technical_by_ticker,
    render_default,
    render_last_report_followup,
    render_technical,
)
from backend.graph.renderers.compare import (
    render_compare,
    render_research_compare,
    requires_research_compare,
)
from backend.graph.renderers.earnings import render_earnings_impact, render_earnings_performance
from backend.graph.renderers.holdings import render_holdings
from backend.graph.renderers.news import render_news_impact
from backend.graph.renderers.opinion import render_investment_opinion
from backend.graph.renderers.portfolio import render_portfolio
from backend.graph.renderers.price import render_price_only
from backend.graph.renderers.valuation import render_valuation_sanity

Renderer = Callable[[GraphState, dict[str, Any]], "str | None"]


def build_render_ctx(state: GraphState) -> dict[str, Any]:
    """原函数头（phase1）：last_report 分支之前可见的公共变量。"""
    query = str(state.get("query") or "").strip()
    ticker_label = ", ".join(_tickers(state)) or "这个标的"
    operations = _operation_names(state)
    memory_context = state.get("memory_context") if isinstance(state.get("memory_context"), dict) else {}
    last_report = current_report_context(memory_context)
    artifacts = state.get("artifacts") if isinstance(state.get("artifacts"), dict) else {}
    decision = artifacts.get("conversation_decision") if isinstance(artifacts.get("conversation_decision"), dict) else {}
    binding = decision.get("context_binding") if isinstance(decision.get("context_binding"), dict) else {}
    render_vars = _render_vars(state)
    return {
        "query": query,
        "ticker_label": ticker_label,
        "operations": operations,
        "memory_context": memory_context,
        "last_report": last_report,
        "artifacts": artifacts,
        "decision": decision,
        "binding": binding,
        "render_vars": render_vars,
    }


def enrich_render_ctx(ctx: dict[str, Any], state: GraphState) -> dict[str, Any]:
    """原函数 prices/news_map 段（phase2）：last_report 分支之后、其余分支之前。"""
    render_vars = ctx["render_vars"]
    prices = _prices_by_ticker(state)
    news_map = _news_by_ticker(state)
    requested_link_count = _requested_news_link_count(state)
    if _reply_contract_requires_links(state):
        requested_link_count = max(requested_link_count, 3)
    if (
        _reply_contract_requires_links(state)
        and requested_link_count
        and _news_article_fallback_allowed(state)
        and not _news_map_has_citable_url(news_map)
    ):
        for ticker, items in _direct_news_article_fallback_map(state, count=requested_link_count).items():
            news_map[ticker] = _dedupe_news_items(items + news_map.get(ticker, []), limit=5)
    technical_map = _technical_by_ticker(state)
    price = next(iter(prices.values()), {})
    news = [item for items in news_map.values() for item in items]
    technical = next(iter(technical_map.values()), "")
    evidence_items = _evidence_items(state)
    ctx.update(
        {
            "prices": prices,
            "news_map": news_map,
            "requested_link_count": requested_link_count,
            "technical_map": technical_map,
            "price": price,
            "news": news,
            "technical": technical,
            "evidence_items": evidence_items,
            "price_snapshot": _useful_render_var(render_vars, "price_snapshot"),
            "technical_snapshot": _useful_render_var(render_vars, "technical_snapshot"),
            "news_summary": _useful_render_var(render_vars, "news_summary"),
            "comparison_conclusion": _useful_render_var(render_vars, "comparison_conclusion"),
            "comparison_metrics": _useful_render_var(render_vars, "comparison_metrics"),
            "conclusion": _useful_render_var(render_vars, "conclusion"),
            "next_watch": _useful_render_var(render_vars, "next_watch"),
            "risks": _useful_render_var(render_vars, "risks"),
            "has_url_context": _has_url_context(state),
        }
    )
    return ctx


# 顺序 = 原 render_chat_markdown 分支出现顺序（见 notes-chat-renderer-map.md 顺序表）。
RENDERERS: list[tuple[str, Renderer]] = [
    ("portfolio", render_portfolio),
    ("url_context", render_url_context),
    ("research_compare", render_research_compare),
    ("earnings_impact", render_earnings_impact),
    ("earnings_performance", render_earnings_performance),
    ("valuation_sanity", render_valuation_sanity),
    ("holdings", render_holdings),
    ("price_only", render_price_only),
    ("compare", render_compare),
    ("investment_opinion", render_investment_opinion),
    ("news_impact", render_news_impact),
    ("technical", render_technical),
    ("default", render_default),
]


OPERATION_LABELS: dict[str, str] = {
    "compare": "对比",
    "price": "价格",
    "macro_brief": "宏观",
    "fetch": "资讯",
    "investment_opinion": "投资观点",
    "technical": "技术面",
    "earnings_impact": "财报影响",
    "news_impact": "新闻影响",
    "qa": "问答",
}


def _task_section_state(state: GraphState, task: dict[str, Any], bucket: dict[str, Any]) -> dict[str, Any]:
    """构造 task 级 state 切片，复用现有渲染函数逐节渲染。"""
    artifacts = state.get("artifacts") if isinstance(state.get("artifacts"), dict) else {}
    step_results = artifacts.get("step_results") if isinstance(artifacts.get("step_results"), dict) else {}
    task_id = str(task.get("id") or "")
    step_ids = [str(sid) for sid in (bucket.get("step_ids") or [])]
    sliced_results: dict[str, Any] = {sid: step_results[sid] for sid in step_ids if sid in step_results}
    for sid, result in (bucket.get("results") or {}).items():
        sliced_results.setdefault(str(sid), result)
    evidence_by_task = (
        artifacts.get("evidence_by_task")
        if isinstance(artifacts.get("evidence_by_task"), dict)
        else {}
    )
    task_evidence = evidence_by_task.get(task_id)
    task_evidence = task_evidence if isinstance(task_evidence, list) else []
    sub_artifacts = {
        "step_results": sliced_results,
        "task_results": {task_id: bucket},
        "evidence_pool": task_evidence,
        "evidence_by_task": {task_id: task_evidence},
    }
    understanding = state.get("understanding") if isinstance(state.get("understanding"), dict) else {}
    operation_obj = task.get("operation") if isinstance(task.get("operation"), dict) else {"name": str(task.get("operation") or "")}
    return {
        **state,
        "understanding": {**understanding, "tasks": [task], "blocked_tasks": []},
        "tasks": [task],
        "blocked_tasks": [],
        "artifacts": sub_artifacts,
        "subject": {
            "subject_type": str(task.get("subject_type") or "unknown"),
            "tickers": list(task.get("tickers") or []),
        },
        "operation": {"name": str(operation_obj.get("name") or "qa")},
    }


def render_task_sections(state: GraphState) -> str | None:
    """多问题 query（≥2 个不同 subject_label 的 task 且 task_results 非空）按任务分节。

    条件不满足返回 None（走既有整体渲染路径）。
    """
    understanding = state.get("understanding") if isinstance(state.get("understanding"), dict) else {}
    tasks = [t for t in (understanding.get("tasks") or []) if isinstance(t, dict)]
    if len(tasks) < 2:
        return None
    labels = {str(t.get("subject_label") or "").strip() for t in tasks}
    labels.discard("")
    if len(labels) < 2:
        return None
    artifacts = state.get("artifacts") if isinstance(state.get("artifacts"), dict) else {}
    task_results = artifacts.get("task_results") if isinstance(artifacts.get("task_results"), dict) else {}
    if not task_results:
        return None

    def _priority(task: dict[str, Any]) -> int:
        try:
            return int(task.get("priority") or 50)
        except Exception:
            return 50

    sections: list[str] = []
    for task in sorted(tasks, key=_priority):
        label = str(task.get("subject_label") or "").strip()
        if not label:
            continue
        task_id = str(task.get("id") or "")
        bucket = task_results.get(task_id)
        if not isinstance(bucket, dict) or not bucket.get("results"):
            continue
        operation_obj = task.get("operation") if isinstance(task.get("operation"), dict) else {"name": str(task.get("operation") or "")}
        op_name = str(operation_obj.get("name") or "").strip() or "qa"
        op_label = OPERATION_LABELS.get(op_name, op_name)
        body = render_chat_markdown(_task_section_state(state, task, bucket)).strip()
        section = f"## {label} · {op_label}"
        if body:
            section = f"{section}\n\n{body}"
        sections.append(section)
    if len(sections) < 2:
        return None
    return "\n\n".join(sections)


def _with_existing_prefixes(markdown: str, state: GraphState) -> str:
    """给分节结果套用既有的 alert 前缀 / blocked 说明包装（与整体渲染同一出口）。"""
    return _finalize_chat_markdown([markdown], state)


def render_chat_markdown(state: GraphState) -> str:
    # compare 是一个跨 task 的整体回答契约。若先按 task 分节，NVDA/AMD 这类
    # 估值比较会被拆成两份 investment_opinion，丢失真正的横向结论。
    if requires_research_compare(state):
        compare_ctx = enrich_render_ctx(build_render_ctx(state), state)
        compared = render_research_compare(state, compare_ctx)
        if compared is not None:
            return compared

    sectioned = render_task_sections(state)
    if sectioned is not None:
        return _with_existing_prefixes(sectioned, state)

    ctx = build_render_ctx(state)
    result = render_last_report_followup(state, ctx)
    if result is not None:
        return result
    enrich_render_ctx(ctx, state)
    for _name, renderer in RENDERERS:
        result = renderer(state, ctx)
        if result is not None:
            return result
    raise AssertionError("render_default must always return a string")
