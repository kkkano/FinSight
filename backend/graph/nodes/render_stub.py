# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import re
from pathlib import Path
from string import Template

from langchain_core.messages import AIMessage

from backend.graph.nodes.compare_gate import should_render_compare, is_compare_operation
from backend.graph.state import GraphState


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


def _append_evidence_section_if_missing(markdown: str, evidence_md: str) -> str:
    if not isinstance(markdown, str) or not markdown.strip():
        return markdown
    if not isinstance(evidence_md, str) or not evidence_md.strip():
        return markdown
    if _contains_markdown_link(markdown):
        return markdown
    return markdown.rstrip() + "\n\n### 引用来源\n\n" + evidence_md + "\n"


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
    if isinstance(existing_draft, str) and len(existing_draft.strip()) >= _NARRATIVE_MIN_CHARS:
        # synthesize already wrote a rich draft; keep it, but inject citations for brief mode if needed.
        if output_mode == "brief":
            evidence_md = _format_evidence_links((artifacts or {}).get("evidence_pool"))
            patched = _append_evidence_section_if_missing(existing_draft, evidence_md)
            if patched != existing_draft:
                artifacts = {**artifacts, "draft_markdown": patched}
        return {"artifacts": artifacts, "messages": [_build_ai_reply_message(artifacts)]}

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
