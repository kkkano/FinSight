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

from collections import Counter
from typing import Any, Callable

from pydantic import Field

from backend.graph.memory_scope import current_report_context
from backend.graph.state import GraphState
from backend.graph.synthesis.contracts import NonEmptyStr, StrictContract
from backend.graph.synthesis.task_outcomes import TaskOutcome

from backend.graph.renderers.shared import (
    _append_sources,
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

STATUS_SUFFIX = {
    "answered": "已回答",
    "partial": "部分完成",
    "unavailable": "暂不可用",
    "blocked": "需要补充",
}

EVIDENCE_LABELS = {
    "price_snapshot": "行情快照",
    "performance_comparison": "可比表现",
    "technical_snapshot": "技术指标",
    "company_profile": "公司资料",
    "fundamental_snapshot": "基本面数据",
    "earnings_estimates": "盈利预期",
    "filing_context": "公司文件",
    "transcript_context": "管理层交流记录",
    "news_context": "新闻资料",
    "event_calendar": "事件日历",
    "holdings_ownership": "持仓与股权资料",
    "macro_context": "宏观资料",
}


class RenderedTaskGroup(StrictContract):
    group_id: NonEmptyStr
    rendered_task_ids: list[NonEmptyStr] = Field(min_length=1)
    markdown: NonEmptyStr


def _outcome_status_detail(outcome: TaskOutcome) -> str:
    if outcome.status == "blocked":
        if "task_missing_subject" in outcome.error_codes:
            return "请补充要分析的股票、指数或其他标的。"
        return "该项仍缺少必要输入或权限，请补充后重试。"
    if outcome.status == "unavailable":
        if "no_successful_result" in outcome.error_codes:
            return "所需数据本次未能取得，请稍后重试。"
        return "当前没有足够的可靠数据回答这一项。"
    if outcome.status == "partial":
        missing = [EVIDENCE_LABELS.get(item, "必要证据") for item in outcome.missing_evidence]
        missing = list(dict.fromkeys(missing))
        if missing:
            return f"已给出有证据支持的部分；仍缺少：{'、'.join(missing)}。"
        return "已给出有证据支持的部分，其余信息本次未能完整取得。"
    return ""


def _task_section_state(
    state: GraphState,
    task: dict[str, Any],
    bucket: dict[str, Any],
    *,
    group_body: bool = False,
) -> dict[str, Any]:
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
        "render_group_body": group_body,
    }
    opinion = artifacts.get("opinion_synthesis") if isinstance(artifacts.get("opinion_synthesis"), dict) else None
    if opinion is not None:
        results = opinion.get("task_results_by_task") if isinstance(opinion.get("task_results_by_task"), dict) else {}
        readiness = opinion.get("readiness_by_task") if isinstance(opinion.get("readiness_by_task"), dict) else {}
        claim_validation = opinion.get("claim_validation") if isinstance(opinion.get("claim_validation"), dict) else {}
        valid_claims = claim_validation.get("valid_claims") if isinstance(claim_validation.get("valid_claims"), dict) else {}
        sliced_claims = {
            claim_id: claim for claim_id, claim in valid_claims.items()
            if isinstance(claim, dict) and str(claim.get("task_id") or "") == task_id
        }
        evidence_normalization = opinion.get("evidence_normalization") if isinstance(opinion.get("evidence_normalization"), dict) else {}
        evidence_index = evidence_normalization.get("evidence_index") if isinstance(evidence_normalization.get("evidence_index"), dict) else {}
        source_ids = {
            str(source_id)
            for claim in sliced_claims.values()
            for source_id in (claim.get("evidence_ids") if isinstance(claim.get("evidence_ids"), list) else [])
        }
        for source_id, evidence in evidence_index.items():
            if isinstance(evidence, dict) and task_id in (evidence.get("task_ids") or []):
                source_ids.add(str(source_id))
        sub_artifacts["opinion_synthesis"] = {
            "evidence_normalization": {
                **evidence_normalization,
                "evidence_index": {key: value for key, value in evidence_index.items() if key in source_ids},
                "evidence_by_task": {task_id: (evidence_normalization.get("evidence_by_task") or {}).get(task_id, [])},
            },
            "claim_validation": {**claim_validation, "valid_claims": sliced_claims},
            "task_results_by_task": {task_id: results[task_id]} if task_id in results else {},
            "readiness_by_task": {task_id: readiness[task_id]} if task_id in readiness else {},
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


def _raw_task_index(state: GraphState) -> dict[str, dict[str, Any]]:
    understanding = state.get("understanding") if isinstance(state.get("understanding"), dict) else {}
    candidates = [
        *(state.get("tasks") if isinstance(state.get("tasks"), list) else []),
        *(understanding.get("tasks") if isinstance(understanding.get("tasks"), list) else []),
        *(state.get("blocked_tasks") if isinstance(state.get("blocked_tasks"), list) else []),
        *(understanding.get("blocked_tasks") if isinstance(understanding.get("blocked_tasks"), list) else []),
    ]
    return {
        str(item.get("id") or item.get("task_id")): item
        for item in candidates
        if isinstance(item, dict) and str(item.get("id") or item.get("task_id") or "").strip()
    }


def _task_from_outcome(outcome: TaskOutcome, raw_index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    raw = raw_index.get(outcome.task_id, {})
    return {
        **raw,
        "id": outcome.task_id,
        "title": outcome.title,
        "subject_label": outcome.subject_label,
        "tickers": list(outcome.tickers),
        "priority": outcome.priority,
        "order_index": outcome.order_index,
        "request_frame_id": outcome.request_frame_id,
        "render_kind": outcome.render_kind,
        "render_group_id": outcome.render_group_id,
        "operation": {"name": outcome.operation},
    }


def _task_bucket(state: GraphState, outcome: TaskOutcome) -> dict[str, Any]:
    artifacts = state.get("artifacts") if isinstance(state.get("artifacts"), dict) else {}
    task_results = artifacts.get("task_results") if isinstance(artifacts.get("task_results"), dict) else {}
    bucket = task_results.get(outcome.task_id)
    if isinstance(bucket, dict):
        return bucket
    step_results = artifacts.get("step_results") if isinstance(artifacts.get("step_results"), dict) else {}
    return {
        "task_id": outcome.task_id,
        "step_ids": list(outcome.required_step_ids),
        "results": {
            step_id: step_results[step_id]
            for step_id in outcome.required_step_ids
            if step_id in step_results
        },
        "errors": [],
    }


def _group_state(
    state: GraphState,
    outcomes: list[TaskOutcome],
    raw_index: dict[str, dict[str, Any]],
) -> GraphState:
    tasks = [_task_from_outcome(outcome, raw_index) for outcome in outcomes]
    task_ids = {outcome.task_id for outcome in outcomes}
    artifacts = state.get("artifacts") if isinstance(state.get("artifacts"), dict) else {}
    raw_evidence = artifacts.get("evidence_by_task") if isinstance(artifacts.get("evidence_by_task"), dict) else {}
    normalized = artifacts.get("task_evidence_normalization") if isinstance(artifacts.get("task_evidence_normalization"), dict) else {}
    normalized_by_task = normalized.get("evidence_by_task") if isinstance(normalized.get("evidence_by_task"), dict) else {}
    evidence_by_task = {
        task_id: raw_evidence.get(task_id, normalized_by_task.get(task_id, []))
        for task_id in task_ids
    }
    evidence_pool = [
        item
        for task_id in [outcome.task_id for outcome in outcomes]
        for item in (evidence_by_task.get(task_id) or [])
        if isinstance(item, dict)
    ]
    seen_sources: set[str] = set()
    evidence_pool = [
        item for item in evidence_pool
        if not (
            (source_id := str(item.get("source_id") or item.get("id") or ""))
            and (source_id in seen_sources or seen_sources.add(source_id))
        )
    ]
    plan = state.get("plan_ir") if isinstance(state.get("plan_ir"), dict) else {}
    steps = [
        step for step in (plan.get("steps") or [])
        if isinstance(step, dict)
        and task_ids.intersection({str(item) for item in (step.get("task_ids") or [])})
    ]
    required_step_ids = {step_id for outcome in outcomes for step_id in outcome.required_step_ids}
    step_results = artifacts.get("step_results") if isinstance(artifacts.get("step_results"), dict) else {}
    sub_artifacts = {
        "render_group_body": True,
        "step_results": {key: value for key, value in step_results.items() if key in required_step_ids},
        "task_results": {outcome.task_id: _task_bucket(state, outcome) for outcome in outcomes},
        "evidence_pool": evidence_pool,
        "evidence_by_task": evidence_by_task,
    }
    frame_ids = {outcome.request_frame_id for outcome in outcomes}
    frames = [
        frame for frame in (state.get("request_frames") or [])
        if isinstance(frame, dict) and str(frame.get("frame_id") or "") in frame_ids
    ]
    tickers = list(dict.fromkeys(ticker for outcome in outcomes for ticker in outcome.tickers))
    understanding = state.get("understanding") if isinstance(state.get("understanding"), dict) else {}
    return {
        **state,
        "tasks": tasks,
        "blocked_tasks": [],
        "understanding": {**understanding, "tasks": tasks, "blocked_tasks": []},
        "subject": {"subject_type": "company" if tickers else "unknown", "tickers": tickers},
        "operation": {"name": outcomes[0].operation if len({item.operation for item in outcomes}) == 1 else "compare"},
        "plan_ir": {**plan, "steps": steps},
        "request_frames": frames,
        "request_frame": frames[0] if len(frames) == 1 else state.get("request_frame"),
        "artifacts": sub_artifacts,
    }


def _aggregate_group_status(outcomes: list[TaskOutcome]) -> str:
    statuses = {item.status for item in outcomes}
    if statuses == {"answered"}:
        return "answered"
    if statuses <= {"unavailable", "blocked"}:
        return "blocked" if statuses == {"blocked"} else "unavailable"
    return "partial"


def _render_group_body(state: GraphState, *, compare_group: bool) -> str:
    ctx = build_render_ctx(state)
    if compare_group and requires_research_compare(state):
        enrich_render_ctx(ctx, state)
        result = render_research_compare(state, ctx)
        if result is not None:
            return result
    result = render_last_report_followup(state, ctx)
    if result is not None:
        return result
    enrich_render_ctx(ctx, state)
    for _name, renderer in RENDERERS:
        result = renderer(state, ctx)
        if result is not None:
            return result
    raise AssertionError("render_default must always return a string")


def _render_group(
    state: GraphState,
    outcomes: list[TaskOutcome],
    raw_index: dict[str, dict[str, Any]],
) -> RenderedTaskGroup:
    group_id = outcomes[0].render_group_id
    is_compare = any(item.render_kind == "compare" for item in outcomes)
    sections: list[str] = []
    if is_compare:
        usable_count = sum(item.status in {"answered", "partial"} for item in outcomes)
        group_status = _aggregate_group_status(outcomes)
        sections.append(f"## 对比结论 · {STATUS_SUFFIX[group_status]}")
        if usable_count >= 2:
            body = _render_group_body(
                _group_state(state, outcomes, raw_index),
                compare_group=True,
            ).strip()
            sections.append(body or "已取得多项可比证据，但本次未能生成可靠的横向结论。")
        else:
            sections.append("可比证据不足，暂不能完成横向判断。")
        for outcome in outcomes:
            detail = _outcome_status_detail(outcome)
            sections.append(f"### {outcome.title} · {STATUS_SUFFIX[outcome.status]}")
            sections.append(detail or "该项证据已纳入上方横向结论。")
    else:
        for outcome in outcomes:
            sections.append(f"## {outcome.title} · {STATUS_SUFFIX[outcome.status]}")
            detail = _outcome_status_detail(outcome)
            if outcome.status in {"answered", "partial"}:
                task = _task_from_outcome(outcome, raw_index)
                body = _render_group_body(
                    _task_section_state(
                        state,
                        task,
                        _task_bucket(state, outcome),
                        group_body=True,
                    ),
                    compare_group=False,
                ).strip()
                if body:
                    sections.append(body)
            if detail:
                sections.append(detail)
            if len(sections) == 1 or sections[-1].startswith("## "):
                sections.append("当前没有可展示的可靠结论。")
    return RenderedTaskGroup(
        group_id=group_id,
        rendered_task_ids=[item.task_id for item in outcomes],
        markdown="\n\n".join(item for item in sections if item.strip()),
    )


def render_task_groups(state: GraphState) -> tuple[str, list[str], bool] | None:
    artifacts = state.get("artifacts") if isinstance(state.get("artifacts"), dict) else {}
    if "task_outcomes" not in artifacts:
        return None
    raw_outcomes = artifacts.get("task_outcomes")
    structural = artifacts.get("task_structural_block_reasons")
    structural = structural if isinstance(structural, list) else []
    try:
        outcomes = [TaskOutcome.model_validate(item) for item in (raw_outcomes or [])]
    except Exception:
        return ("内部质量检查未通过，本次无法可靠生成回答。\n", [], False)
    if not outcomes or "task_coverage_mismatch" in structural:
        return ("内部任务覆盖检查未通过，本次无法可靠生成回答。\n", [], False)

    grouped: dict[str, list[TaskOutcome]] = {}
    for outcome in sorted(outcomes, key=lambda item: (item.priority, item.order_index)):
        grouped.setdefault(outcome.render_group_id, []).append(outcome)
    ordered_groups = sorted(
        grouped.values(),
        key=lambda items: (min(item.priority for item in items), min(item.order_index for item in items)),
    )
    raw_index = _raw_task_index(state)
    rendered_groups = [_render_group(state, items, raw_index) for items in ordered_groups]
    rendered_ids = [task_id for group in rendered_groups for task_id in group.rendered_task_ids]
    expected_ids = [item.task_id for item in sorted(outcomes, key=lambda item: (item.priority, item.order_index))]
    coverage_ok = Counter(rendered_ids) == Counter(expected_ids) and len(rendered_ids) == len(set(rendered_ids))
    if not coverage_ok:
        return ("内部任务渲染检查未通过，本次无法可靠生成回答。\n", rendered_ids, False)

    lines = [group.markdown for group in rendered_groups]
    _append_sources(lines, _evidence_items(state))
    return (_finalize_chat_markdown(lines, state), rendered_ids, True)


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
    grouped = render_task_groups(state)
    if grouped is not None:
        return grouped[0]

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
