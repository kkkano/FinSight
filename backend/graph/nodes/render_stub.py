# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import re
import json
from pathlib import Path
from string import Template
from urllib.parse import quote_plus

from langchain_core.messages import AIMessage

from backend.graph.nodes.chat_renderer import render_chat_markdown
from backend.graph.nodes.compare_gate import should_render_compare, is_compare_operation
from backend.graph.state import GraphState
from backend.utils.quote import parse_quote_payload


def _build_ai_reply_message(artifacts: dict) -> AIMessage:
    """
    Extract a concise summary from artifacts to persist as AIMessage
    in the checkpointer's message history.

    This enables multi-turn conversation context without storing
    the full draft_markdown (which can be 4000-6000 chars) in messages.
    """
    _MAX_SUMMARY_CHARS = 500

    draft = artifacts.get("draft_markdown") if isinstance(artifacts, dict) else None
    if isinstance(draft, str) and draft.strip():
        text = draft.strip()
        # Strip leading markdown headers for cleaner summary
        lines = text.splitlines()
        content_lines = [
            ln for ln in lines
            if not ln.strip().startswith("#") and ln.strip()
        ]
        summary = "\n".join(content_lines).strip()
        if not summary:
            summary = text
        if len(summary) > _MAX_SUMMARY_CHARS:
            summary = summary[:_MAX_SUMMARY_CHARS] + "..."
        return AIMessage(content=summary)

    # Fallback: chat response or generic marker
    response = artifacts.get("response") if isinstance(artifacts, dict) else None
    if isinstance(response, str) and response.strip():
        text = response.strip()
        if len(text) > _MAX_SUMMARY_CHARS:
            text = text[:_MAX_SUMMARY_CHARS] + "..."
        return AIMessage(content=text)

    return AIMessage(content="(analysis completed)")



def _contains_markdown_link(text: str) -> bool:
    if not isinstance(text, str) or not text.strip():
        return False
    return bool(re.search(r"\[[^\]]+\]\(https?://[^)]+\)", text))


def _format_evidence_links(evidence_pool: list[dict] | None) -> str:
    if not isinstance(evidence_pool, list) or not evidence_pool:
        return ""
    lines: list[str] = []
    for item in evidence_pool:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "(untitled)").strip()
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        source = str(item.get("source") or "").strip()
        ts = str(item.get("published_date") or "").strip()
        meta = " / ".join([x for x in (source, ts) if x])
        lines.append(f"- [{title}]({url})" + (f" ({meta})" if meta else ""))
        if len(lines) >= 6:
            break
    return "\n".join(lines)


def _parse_jsonish_output(output: object) -> object:
    if not isinstance(output, str):
        return output
    text = output.strip()
    if not text:
        return output
    if not (text.startswith("[") or text.startswith("{")):
        return output
    try:
        return json.loads(text)
    except Exception:
        return output


def _format_source_item(item: dict) -> str:
    title = str(
        item.get("title")
        or item.get("headline")
        or item.get("summary")
        or item.get("name")
        or "(untitled)"
    ).strip()
    url = str(item.get("url") or item.get("link") or item.get("article_url") or "").strip()
    source = str(item.get("source") or item.get("publisher") or "").strip()
    published = str(
        item.get("published_at")
        or item.get("published_date")
        or item.get("datetime")
        or item.get("date")
        or ""
    ).strip()
    meta = " / ".join(part for part in (source, published[:10] if published else "") if part)
    label = f"[{title}]({url})" if url.startswith(("http://", "https://")) else title
    return label + (f"（{meta}）" if meta else "")


def _extract_source_lines(output: object, limit: int = 5) -> list[str]:
    parsed = _parse_jsonish_output(output)
    rows: list[object]
    if isinstance(parsed, list):
        rows = parsed
    elif isinstance(parsed, dict):
        nested = parsed.get("articles") or parsed.get("items") or parsed.get("news") or parsed.get("results") or parsed.get("releases")
        rows = nested if isinstance(nested, list) else [parsed]
    else:
        return []

    lines: list[str] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        line = _format_source_item(item)
        if line and line not in lines:
            lines.append(line)
        if len(lines) >= limit:
            break
    return lines


def _append_evidence_section_if_missing(markdown: str, evidence_md: str) -> str:
    if not isinstance(markdown, str) or not markdown.strip():
        return markdown
    if not isinstance(evidence_md, str) or not evidence_md.strip():
        return markdown
    if _contains_markdown_link(markdown):
        return markdown
    return markdown.rstrip() + "\n\n### 引用来源\n\n" + evidence_md + "\n"


def _task_operation_name(task: dict) -> str:
    operation = task.get("operation")
    if isinstance(operation, dict):
        name = operation.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return "qa"


def _task_tickers(task: dict) -> list[str]:
    values = task.get("tickers")
    if not isinstance(values, list):
        return []
    tickers: list[str] = []
    seen: set[str] = set()
    for value in values:
        ticker = str(value or "").strip().upper()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        tickers.append(ticker)
    return tickers


def _impact_takeaway(task: dict, related: list[str]) -> str:
    op_name = _task_operation_name(task)
    if op_name != "analyze_impact":
        return ""

    subject_type = str(task.get("subject_type") or "").strip().lower()
    label = str(task.get("subject_label") or ", ".join(_task_tickers(task)) or subject_type or "该对象").strip()
    joined = " ".join(related)

    if subject_type == "macro":
        if related:
            return f"结论：{label} 对市场的影响主要看通胀读数是否改变降息/利率预期；当前证据不足以给出单边判断。"
        return f"结论：{label} 需要先补充官方发布时间和实际读数，才能判断对估值和风险偏好的方向。"

    if re.search(r"\b(price|current price|change:|涨|跌|deliveries|delivery|交付|margin|earnings|guidance)\b", joined, re.IGNORECASE):
        return f"结论：{label} 当前更适合按“事件驱动 + 价格反应”跟踪；已有新闻/价格信号可用于判断短线情绪，但还不能单独构成投资结论。"

    if related:
        return f"结论：{label} 已找到相关新闻线索，下一步应确认事件是否影响交付、利润率、监管风险或估值预期。"

    return f"结论：{label} 暂无足够证据判断影响方向，需要补充最新新闻、价格和财报/交付数据。"


def _sanitize_user_facing_snippet(text: object) -> str:
    cleaned = str(text or "").strip()
    cleaned = re.sub(r"\s*\|\s*Suggested ladder:.*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.replace("Suggested ladder", "")
    return cleaned.strip()


def _summarize_step_output(output: object) -> list[str]:
    source_lines = _extract_source_lines(output, limit=3)
    if source_lines:
        return source_lines

    if _looks_like_quote_output(output):
        quote = parse_quote_payload(output)
        if quote:
            price = quote.get("price")
            change = quote.get("change")
            change_percent = quote.get("change_percent")
            parts = [f"最新价格约为 {float(price):.2f} USD"]
            if change is not None:
                parts.append(f"变动 {float(change):+.2f}")
            if change_percent is not None:
                parts.append(f"{float(change_percent):+.2f}%")
            return ["，".join(parts) + "。"]

    if isinstance(output, dict) and output.get("skipped"):
        reason = str(output.get("reason") or "skipped")
        return [f"已规划，当前执行环境未运行实时工具（{reason}）。"]
    if isinstance(output, str):
        text = _sanitize_user_facing_snippet(output)
        if not text:
            return []
        return [text[:220]]
    if isinstance(output, list):
        lines: list[str] = []
        for item in output[:3]:
            if isinstance(item, dict):
                title = str(item.get("title") or item.get("headline") or item.get("summary") or "").strip()
                source = str(item.get("source") or "").strip()
                if title:
                    lines.append(title + (f"（{source}）" if source else ""))
            elif isinstance(item, str) and item.strip():
                lines.append(_sanitize_user_facing_snippet(item)[:180])
        return lines
    if isinstance(output, dict):
        for key in ("summary", "title", "headline", "snippet", "raw"):
            value = output.get(key)
            if isinstance(value, str) and value.strip():
                return [_sanitize_user_facing_snippet(value)[:220]]
        articles = output.get("articles") or output.get("items") or output.get("news") or output.get("results")
        if isinstance(articles, list):
            return _summarize_step_output(articles)
        compact = ", ".join(f"{key}={value}" for key, value in list(output.items())[:5] if value is not None)
        return [_sanitize_user_facing_snippet(compact)[:220]] if compact else []
    return []


def _looks_like_quote_output(output: object) -> bool:
    if isinstance(output, dict):
        return "price" in output or (isinstance(output.get("data"), dict) and "price" in output["data"])
    if not isinstance(output, str):
        return False
    text = output.strip()
    if text.startswith(("{", "[")):
        return False
    return bool(re.search(r"\b(Current Price|Change:)\b", text, re.IGNORECASE))


def _user_facing_step_label(step: dict, fallback_step_id: str) -> str:
    name = str(step.get("name") or fallback_step_id).strip()
    labels = {
        "get_stock_price": "价格",
        "get_company_news": "新闻",
        "get_company_info": "公司信息",
        "get_technical_snapshot": "技术面",
        "get_performance_comparison": "表现对比",
        "get_official_macro_releases": "官方宏观发布",
        "get_authoritative_media_news": "权威新闻",
        "get_factor_exposure": "组合暴露",
        "run_portfolio_stress_test": "组合压力测试",
        "search": "搜索",
        "price_agent": "价格分析",
        "news_agent": "新闻分析",
        "fundamental_agent": "基本面分析",
        "technical_agent": "技术分析",
        "macro_agent": "宏观分析",
        "risk_agent": "风险分析",
    }
    return labels.get(name, "证据")


def _empty_task_line(task: dict, *, is_report_mode: bool) -> str:
    op_name = _task_operation_name(task)
    tickers = ", ".join(_task_tickers(task))
    target = str(task.get("subject_label") or tickers or task.get("subject_type") or "这部分").strip()
    if op_name == "compare":
        return f"{target} 的直接对比证据还不够完整；先结合下方价格、新闻和基本面线索阅读。"
    if op_name == "price":
        return f"{target} 暂时没有拿到可用的实时价格数据。"
    if op_name in {"fetch", "news"}:
        return f"{target} 暂时没有拿到可引用的最新新闻来源。"
    if op_name in {"company_info", "fundamental"}:
        return f"{target} 暂时没有拿到可用的公司信息补充。"
    if op_name == "technical":
        return f"{target} 暂时没有拿到可用的技术面数据。"
    if is_report_mode:
        return f"{target} 仍需要更多证据补充，当前不强行下结论。"
    return f"{target} 这部分证据还不够，我先不硬编结论。"


def _display_time_scope_label(raw_label: object) -> str:
    label = str(raw_label or "").strip()
    if not label:
        return ""
    if label.lower() in {"unspecified", "unknown", "none", "default"}:
        return ""
    return label


def _build_multitask_markdown(state: GraphState, artifacts: dict) -> str:
    tasks = state.get("tasks")
    ready_tasks = [task for task in (tasks if isinstance(tasks, list) else []) if isinstance(task, dict)]
    blocked_tasks = state.get("blocked_tasks")
    blocked = [task for task in (blocked_tasks if isinstance(blocked_tasks, list) else []) if isinstance(task, dict)]
    if len(ready_tasks) <= 1 and not blocked:
        return ""

    plan_ir = state.get("plan_ir") if isinstance(state.get("plan_ir"), dict) else {}
    steps = plan_ir.get("steps") if isinstance(plan_ir.get("steps"), list) else []
    step_results = artifacts.get("step_results") if isinstance(artifacts.get("step_results"), dict) else {}
    step_index = {str(step.get("id")): step for step in steps if isinstance(step, dict) and step.get("id")}

    explicit_task_binding = any(
        isinstance(step, dict)
        and any(str(value or "").strip() for value in (step.get("task_ids") or []))
        for step in steps
    )

    def _related_outputs(task: dict) -> list[str]:
        task_id = str(task.get("id") or "").strip()
        tickers = set(_task_tickers(task))
        subject_type = str(task.get("subject_type") or "").strip().lower()
        related: list[str] = []
        def _format_related_line(step: dict, fallback_step_id: str, line: str) -> str:
            name = str(step.get("name") or fallback_step_id).strip()
            label = _user_facing_step_label(step, fallback_step_id)
            if name == "search" and not _contains_markdown_link(line):
                inputs = step.get("inputs") if isinstance(step.get("inputs"), dict) else {}
                search_query = str(inputs.get("query") or state.get("query") or line[:120]).strip()
                if search_query:
                    line = f"{line} ([搜索来源](https://www.google.com/search?q={quote_plus(search_query)}))"
            return f"{label}: {line}"

        for step_id, result in step_results.items():
            if not isinstance(result, dict):
                continue
            step = step_index.get(str(step_id))
            if not isinstance(step, dict):
                continue
            step_task_ids = [str(value or "").strip() for value in (step.get("task_ids") or []) if str(value or "").strip()]
            if task_id and task_id in step_task_ids:
                for line in _summarize_step_output(result.get("output")):
                    related.append(_format_related_line(step, str(step_id), line))
                    if len(related) >= 3:
                        return related
                continue
            if explicit_task_binding and step_task_ids:
                continue
            inputs = step.get("inputs") if isinstance(step.get("inputs"), dict) else {}
            ticker = str(inputs.get("ticker") or "").strip().upper()
            name = str(step.get("name") or "").strip()
            is_related = bool(ticker and ticker in tickers)
            if subject_type == "macro" and name in {"get_official_macro_releases", "get_authoritative_media_news", "search"}:
                is_related = True
            if subject_type == "portfolio" and name in {"get_factor_exposure", "run_portfolio_stress_test", "search"}:
                is_related = True
            if not is_related:
                continue
            for line in _summarize_step_output(result.get("output")):
                related.append(_format_related_line(step, str(step_id), line))
                if len(related) >= 3:
                    return related
        return related

    output_mode = str(state.get("output_mode") or "brief").strip().lower()
    is_report_mode = output_mode == "investment_report"
    if is_report_mode:
        subject = state.get("subject") if isinstance(state.get("subject"), dict) else {}
        tickers = subject.get("tickers") if isinstance(subject.get("tickers"), list) else []
        ticker_label = " vs ".join(str(t).strip().upper() for t in tickers if str(t).strip()) or "多主题"
        lines = [f"## {ticker_label} 研究报告", ""]
        if blocked:
            lines.extend([f"有 {len(blocked)} 个信息点还需要补充，先基于已拿到的证据给出可用结论。", ""])
    else:
        lines = [
            "我先按不同对象分开说：",
            "",
        ]

    for idx, task in enumerate(ready_tasks[:8], 1):
        tickers = _task_tickers(task)
        label = str(task.get("subject_label") or ", ".join(tickers) or task.get("subject_type") or f"任务 {idx}")
        op_name = _task_operation_name(task)
        time_scope = task.get("time_scope") if isinstance(task.get("time_scope"), dict) else {}
        scope_label = _display_time_scope_label(time_scope.get("label") or time_scope.get("kind"))
        title_suffix = f"（{scope_label}）" if scope_label else ""
        if is_report_mode:
            lines.extend([f"### {idx}. {label}{title_suffix}", ""])
        else:
            lines.extend([f"{label}{title_suffix}：", ""])
        related = _related_outputs(task)
        takeaway = _impact_takeaway(task, related)
        if takeaway:
            lines.append(f"- {takeaway}")
        if related:
            lines.extend(f"- {item}" for item in related)
        else:
            lines.append(f"- {_empty_task_line(task, is_report_mode=is_report_mode)}")
        lines.append("")

    if blocked:
        lines.extend(["### 需要补充的信息" if is_report_mode else "还缺的信息：", ""])
        for item in blocked[:5]:
            reason = str(item.get("reason") or "blocked")
            question = str(item.get("question") or "").strip()
            lines.append(f"- {reason}" + (f"：{question}" if question else ""))
        lines.append("")

    lines.append("> 以上为研究辅助信息，不构成投资建议。")
    return "\n".join(lines).strip() + "\n"


def render_stub(state: GraphState) -> dict:
    """
    Phase 4 template renderer.
    Render markdown by subject_type + output_mode.

    IMPORTANT: If the upstream *synthesize* node already produced a substantial
    ``draft_markdown`` (e.g. via narrative / llm mode), we preserve it as-is
    and skip template rendering.  Template rendering is only a **fallback**
    for stub / empty drafts.
    """
    # ── Early-return: morning_brief pass-through (no template needed) ──
    _brief_op = (state.get("operation") or {}).get("name") if isinstance(state.get("operation"), dict) else None
    artifacts = state.get("artifacts") or {}
    if _brief_op == "morning_brief":
        brief_draft = artifacts.get("draft_markdown") if isinstance(artifacts, dict) else None
        if isinstance(brief_draft, str) and brief_draft.strip():
            return {"artifacts": artifacts, "messages": [_build_ai_reply_message(artifacts)]}

    # ── Early-return: honour existing narrative draft ──────────────
    _NARRATIVE_MIN_CHARS = int(os.getenv("RENDER_NARRATIVE_MIN_CHARS", "500"))
    output_mode = state.get("output_mode", "brief")
    existing_draft = artifacts.get("draft_markdown") if isinstance(artifacts, dict) else None
    if output_mode in {"chat", "brief"}:
        markdown = render_chat_markdown(state)
        if not str(markdown or "").strip():
            markdown = _build_multitask_markdown(state, artifacts if isinstance(artifacts, dict) else {})
        if not str(markdown or "").strip():
            markdown = "这轮没有合成出可用文字，但上下文已经保留。你可以直接重试这句，我会继续按当前问题处理。\n"
        result_artifacts = {**(state.get("artifacts") or {}), "draft_markdown": markdown}
        return {"artifacts": result_artifacts, "messages": [_build_ai_reply_message(result_artifacts)]}

    if isinstance(existing_draft, str) and len(existing_draft.strip()) >= _NARRATIVE_MIN_CHARS:
        # synthesize already wrote a rich draft; keep it, but inject citations for brief mode if needed.
        if output_mode == "brief":
            evidence_md = _format_evidence_links((artifacts or {}).get("evidence_pool"))
            patched = _append_evidence_section_if_missing(existing_draft, evidence_md)
            if patched != existing_draft:
                artifacts = {**artifacts, "draft_markdown": patched}
        return {"artifacts": artifacts, "messages": [_build_ai_reply_message(artifacts)]}

    multitask_markdown = _build_multitask_markdown(state, artifacts if isinstance(artifacts, dict) else {})
    if multitask_markdown:
        result_artifacts = {**(state.get("artifacts") or {}), "draft_markdown": multitask_markdown}
        return {"artifacts": result_artifacts, "messages": [_build_ai_reply_message(result_artifacts)]}

    # ── Regular template rendering (stub / thin-draft fallback) ───
    subject = state.get("subject") or {}
    subject_type = subject.get("subject_type", "unknown")
    output_mode = state.get("output_mode", "brief")
    query = state.get("query") or ""
    operation = (state.get("operation") or {}).get("name") or "qa"

    if subject_type == "unknown":
        # Guardrail: clarification prompts must be emitted only from the Clarify node.
        markdown = "> (internal) unexpected state: `unknown` subject reached Render.\n"
        result_artifacts = {**(state.get("artifacts") or {}), "draft_markdown": markdown}
        return {"artifacts": result_artifacts, "messages": [_build_ai_reply_message(result_artifacts)]}

    tickers = subject.get("tickers") if isinstance(subject, dict) else None
    ticker = (tickers or [None])[0] if isinstance(tickers, list) else None
    tickers_label = " vs ".join([t for t in (tickers or []) if isinstance(t, str) and t.strip()][:4]) if isinstance(tickers, list) and len(tickers) > 1 else (ticker or "N/A")
    if subject_type == "macro":
        tickers_label = "宏观主题"
    selection_payload = subject.get("selection_payload") if isinstance(subject, dict) else None
    selection_payload = selection_payload if isinstance(selection_payload, list) else []

    def _fmt_selection_list() -> str:
        if not selection_payload:
            return "- （未提供 selection）"
        lines = []
        for s in selection_payload[:8]:
            if not isinstance(s, dict):
                continue
            title = s.get("title") or s.get("headline") or "(untitled)"
            src = s.get("source")
            ts = s.get("ts") or s.get("datetime") or s.get("published_at")
            url = s.get("url")
            meta = " / ".join([x for x in [src, ts] if x])
            if url:
                lines.append(f"- [{title}]({url})" + (f"（{meta}）" if meta else ""))
            else:
                lines.append(f"- {title}" + (f"（{meta}）" if meta else ""))
            snippet = s.get("snippet") or s.get("summary")
            if snippet:
                lines.append(f"  - {str(snippet).strip()}")
        return "\n".join(lines) if lines else "- （selection 为空）"

    def _fmt_executor_evidence() -> str:
        # brief mode always shows evidence links when available
        if output_mode == "brief":
            show_evidence = True
        else:
            raw_setting = os.getenv("LANGGRAPH_SHOW_EVIDENCE")
            show_evidence = False if raw_setting is None else raw_setting.lower() in ("true", "1", "yes", "on")

        if not show_evidence:
            return ""

        evidence_md = _format_evidence_links((artifacts or {}).get("evidence_pool"))
        if evidence_md:
            return evidence_md

        # Do not leak internal executor step_results into user-facing markdown.
        # The UI already exposes structured traces in the "Agent Trace" panel.
        return ""

    def _fmt_section_citations() -> str:
        artifacts_local = state.get("artifacts") or {}
        evidence_pool = artifacts_local.get("evidence_pool") if isinstance(artifacts_local, dict) else None
        if not isinstance(evidence_pool, list) or not evidence_pool:
            return "- （暂无 section 级引用）"

        patterns = [
            re.compile(r"\bItem\s+(\d+[A-Za-z]?)\b", flags=re.IGNORECASE),
            re.compile(r"\bNote\s+(\d+[A-Za-z]?)\b", flags=re.IGNORECASE),
            re.compile(r"\bPart\s+([IVX]+)\b", flags=re.IGNORECASE),
        ]
        section_hits: dict[str, list[str]] = {}

        for item in evidence_pool:
            if not isinstance(item, dict):
                continue
            text = " ".join([str(item.get("title") or ""), str(item.get("snippet") or "")])
            if not text.strip():
                continue
            section_ref = None
            for pattern in patterns:
                match = pattern.search(text)
                if not match:
                    continue
                key = pattern.pattern.lower()
                value = match.group(1).upper()
                if "item" in key:
                    section_ref = f"Item {value}"
                elif "note" in key:
                    section_ref = f"Note {value}"
                elif "part" in key:
                    section_ref = f"Part {value}"
                break
            if not section_ref:
                continue

            title = str(item.get("title") or section_ref).strip()
            url = str(item.get("url") or "").strip()
            label = f"[{title}]({url})" if url else title

            section_hits.setdefault(section_ref, [])
            if label not in section_hits[section_ref]:
                section_hits[section_ref].append(label)

        if not section_hits:
            return "- （暂无 section 级引用）"

        lines = []
        for section in sorted(section_hits.keys()):
            refs = "; ".join(section_hits[section][:3])
            lines.append(f"- {section}: {refs}")
            if len(lines) >= 8:
                break
        return "\n".join(lines) if lines else "- （暂无 section 级引用）"

    template_key = None
    if subject_type in ("news_item", "news_set"):
        template_key = "news_report" if output_mode == "investment_report" else "news_brief"
    elif subject_type == "company":
        # Special-case: company news fetching should not use the generic company brief template.
        if operation == "fetch" and (not isinstance(tickers, list) or len(tickers) <= 1):
            template_key = "company_news_report" if output_mode == "investment_report" else "company_news_brief"
        # Multi-ticker compare -> dedicated template.
        # Requires BOTH operation=compare AND valid tool evidence (see compare_gate).
        # When evidence is missing, should_render_compare returns False and we
        # fall through to the normal company template.  The decision_note is
        # emitted upstream in synthesize.
        elif should_render_compare(state):
            template_key = "company_compare_report" if output_mode == "investment_report" else "company_compare_brief"
        else:
            template_key = "company_report" if output_mode == "investment_report" else "company_brief"
    elif subject_type in ("filing", "research_doc"):
        template_key = "filing_report" if output_mode == "investment_report" else "filing_brief"
    elif subject_type == "macro":
        template_key = "company_report" if output_mode == "investment_report" else "company_brief"

    note_prefix = ""
    if not template_key:
        # Unknown subject_type -> fall back to brief generic output
        note_prefix = "> （模板缺失已降级：unknown subject）\n\n"
        template_key = "company_brief"

    template_dir = Path(__file__).resolve().parents[1] / "templates"
    template_path = template_dir / f"{template_key}.md"
    if not template_path.exists():
        note_prefix = f"> （模板缺失已降级：{template_key}）\n\n"
        template_path = template_dir / "company_brief.md"

    template_text = template_path.read_text(encoding="utf-8")
    tpl = Template(template_text)

    artifacts = state.get("artifacts") or {}
    render_vars = artifacts.get("render_vars") if isinstance(artifacts, dict) else None

    values = {
        "query": query,
        "ticker": tickers_label,
        "tickers": tickers_label,
        # news templates
        "news_summary": _fmt_selection_list(),
        "impact_analysis": "\n".join(
            [
                f"- operation=`{operation}`：基于当前上下文给出结构化影响分析（非投资建议）。",
                "- 影响路径：事件 → 预期/情绪 → 业绩预期 → 估值/价格。",
                "- 如需更深入：可启用 live tools 或点击“生成研报”。",
            ]
        ),
        "next_watch": "\n".join(
            [
                "- 关注点：后续公告/财报指引、监管进展、竞争对手动态。",
                "- 验证：价格反应/成交量/波动是否与叙事一致。",
            ]
        ),
        "risks": "\n".join(
            [
                "- 信息可能不完整；建议结合更多来源交叉验证。",
                "- 输出不构成投资建议。",
            ]
        ),
        # company templates
        "conclusion": "\n".join(
            [
                "- 当前缺少明确对象/证据（可选择新闻/财报/文档或提供 ticker）。",
                "- 我可以按：事件/基本面/估值/风险 的结构输出结论（非投资建议）。",
            ]
        ),
        "price_snapshot": "- （暂无价格数据）",
        "technical_snapshot": "- （暂无技术指标数据）",
        "comparison_conclusion": "- （暂无可用数据，无法形成对比结论）",
        "comparison_metrics": "- （暂无绩效对比数据）",
        "evidence": _fmt_executor_evidence(),
        "investment_summary": "\n".join(
            [
                "- 研报为结构化交付物：更长、更全面，但不等于“必须跑全家桶”。",
                "- 如缺少关键证据，会明确标注缺口与建议补充项。",
            ]
        ),
        "company_overview": "\n".join(
            [
                "- 公司概况：当前未执行公司信息工具；如需可启用 live tools 补齐。",
                "- 建议补齐：主营/行业/地区、关键产品、商业模式与主要风险。",
            ]
        ),
        "catalysts": "\n".join(
            [
                "- 可能催化：财报、产品发布、政策变化、行业景气度变化。",
                "- 将基于新闻/财报证据进一步细化。",
            ]
        ),
        "valuation": "\n".join(
            [
                "- 估值与财务：当前未执行实时价格/财务工具；如需可启用 live tools。",
                "- 常见框架：增长 vs 估值倍数、盈利质量、现金流与风险溢价。",
            ]
        ),
        # filing/doc templates
        "summary": _fmt_selection_list(),
        "highlights": "\n".join(
            [
                "- 建议抽取：营收/利润/毛利率、指引、分部表现、一次性项目。",
                "- 若为公告：关注口径变化、重大事项、潜在法律/监管风险。",
            ]
        ),
        "analysis": "\n".join(
            [
                f"- operation=`{operation}`：基于文档内容做结构化解读与影响路径（非投资建议）。",
                "- 如需更深入章节，请点击“生成研报”。",
            ]
        ),
        "section_citations": _fmt_section_citations(),
    }

    if isinstance(render_vars, dict):
        for key, value in render_vars.items():
            if isinstance(value, str) and value.strip():
                values[key] = value

    markdown = note_prefix + tpl.safe_substitute(values)
    result_artifacts = {**(state.get("artifacts") or {}), "draft_markdown": markdown}
    return {"artifacts": result_artifacts, "messages": [_build_ai_reply_message(result_artifacts)]}
