# -*- coding: utf-8 -*-
"""ResearchSynthesisDraft 的唯一 Markdown renderer。"""
from __future__ import annotations

import json
import re
from urllib.parse import urlsplit
from typing import Any

from backend.graph.synthesis.contracts import ReportSynthesisDraft, ResearchReportRenderResult, aggregate_task_status
from backend.graph.synthesis.requirement_validation import claim_has_reliable_sources, evaluate_answer_requirements, overall_conclusion_block_reasons
from backend.graph.synthesis.research_synthesis import clean_research_text
from backend.graph.renderers.fact_formatters import format_fact, number
from backend.graph.renderers.content_selection import DIMENSION_KINDS, select_claims, select_fact_ids
from backend.research.news_event_quality import canonical_news_url

_STATUS_LABEL = {
    "answered": "已回答",
    "partial": "部分完成",
    "unavailable": "证据不足",
    "blocked": "需要补充信息",
}


def _public_text(value: str) -> str:
    """只清理展示层的内部引用/字段写法，证据与原始 Claim 保持原样。"""
    text = clean_research_text(value)
    text = re.sub(r'[（(]\s*[EC]\d+(?:\s*[、,，/–—-]\s*[EC]?\d+)*\s*[)）]', '', text)
    text = re.sub(r'[（(]\s*direction\s*=\s*(?:future|past)\s*[、,，]\s*(?:days_ahead|hours_back)\s*=\s*\d+(?:\.\d+)?\s*[)）]', '', text)
    replacements = {
        r'(?:coverage_window\.)?exhaustive\s*[=:]\s*false': '并非完整事件清单',
        r'(?:coverage_window\.)?exhaustive\s*[=:]\s*true': '来源声明已完整覆盖',
        r'status\s*[=:]\s*scheduled': '已排期',
        r'verification\s*[=:]\s*provider_reported': '由供应商提供，尚未获官方确认',
        r'(?:根据|依据)\s*E\d+(?![A-Za-z0-9_])': '根据已核实来源',
        r'E\d+(?=明确(?:标注|说明)|提供|给出)': '来源',
        r'dividends_included\s*(?:为|[=:])\s*false': '未计入现金分红',
        r'dividends_included\s*(?:为|[=:])\s*true': '已计入现金分红',
    }
    for pattern, replacement in replacements.items():
        text = re.sub(pattern, replacement, text, flags=re.I)
    return text


def _line(value: str) -> str:
    compact = " ".join(_public_text(value).split())
    return re.sub(r"(?<![\w:])(-?\d+\.\d{5,})(?!\w)", lambda match: number(match.group(1), 4), compact)


def _requirement_gap_text(missing: dict[str, Any]) -> str:
    reasons = str(missing.get("reason") or "").split(",")
    labels = {
        "requirement_unsupported": "当前尚无对应的数据或计算能力",
        "requirement_input_missing": "需要补充输入资料",
        "requirement_period_unverified": "现有证据的期间与请求不匹配",
        "requirement_explanation_missing": "解释尚未通过对应来源校验",
        "requirement_evidence_missing": "尚未取得符合要求的证据",
        "requirement_evidence_not_presented": "相关证据尚未完整展示",
        "capital_allocation_period_mismatch": "现金项目未对齐同一期间和币种",
        "requirement_official_declaration_missing": "尚未核实官方宣告正文",
        "requirement_declaration_currency_unverified": "原始宣告未明确币种",
        "requirement_time_window_unverified": "尚未核实所要求的时间窗口",
        "requirement_primary_source_missing": "尚未取得对应原始官方来源",
        "requirement_traceable_source_missing": "来源或数据时点不足以追溯",
        "requirement_employment_period_mismatch": "就业指标没有对齐同一报告月份",
    }
    notes = list(dict.fromkeys(labels[reason] for reason in reasons if reason in labels))
    description = _line(str(missing["description"]))
    return description + (f"（{'；'.join(notes)}）" if notes else "")


_KIND_LABELS = {
    "price_snapshot": "价格", "company_profile": "公司与估值",
    "earnings_estimates": "盈利预期", "fundamental_snapshot": "基本面",
    "technical_snapshot": "技术面", "news_context": "新闻与催化剂",
    "risk_profile": "风险", "macro_context": "宏观事件",
    "filing_context": "财务与公告", "performance_comparison": "表现比较",
    "holdings_ownership": "持仓与股权", "options_derivatives": "期权",
    "event_calendar": "事件日历", "transcript_context": "管理层指引",
    "document_context": "文档事实", "unknown": "证据",
    "price_window": "区间价格与计算", "capital_allocation": "现金分配与股数",
}

_DIMENSION_LABELS = {
    "fundamental_quality": "基本面",
    "valuation_reasonableness": "估值合理性",
    "business_model": "业务与商业模式",
    "competition": "竞争格局",
    "risk_level": "风险",
    "earnings_impact": "财报影响",
    "trend_quality": "趋势质量",
    "technical_quality": "技术面",
    "news_catalysts": "催化剂",
    "external_impact": "宏观影响",
    "performance": "表现",
}


def _value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _fact_text(evidence, profile: str = "full") -> str:
    return format_fact(evidence, profile=profile)


def _requires_investment_direction(task) -> bool:
    dimensions = set(task.requested_dimensions)
    dimensions.update(str(item.get("dimension") or "") for item in task.answer_requirements)
    if dimensions or task.answer_requirements:
        return bool(dimensions & {"investment_attractiveness", "investment_opinion", "investment_thesis", "investment_direction"})
    return task.operation == "investment_opinion"


def _source_label(evidence) -> str:
    title = clean_research_text(evidence.title or "")
    if not title or re.search(r"(?:get_|_agent|\boutput\b|\bevidence\s*\d)", title):
        title = f"{evidence.subject or ''} {_KIND_LABELS.get(evidence.kind, '研究证据')}".strip()
    source = evidence.source_name or ""
    if re.search(r"(?:get_|_agent)", source):
        source = ""
    origin = urlsplit(evidence.url or "").hostname
    if origin and source and "." in source and origin.removeprefix("www.") != source.removeprefix("www."):
        source = f"{origin}（经 {source}）"
    return " / ".join(value for value in (title, source, evidence.as_of or evidence.period_end or "") if value)


def _comparison_lines(draft: ReportSynthesisDraft, task, refs) -> tuple[list[str], set[str]]:
    selected_ids = select_fact_ids(draft, task, "comparison")
    used_sources = set()
    by_subject = {}
    for source_id in selected_ids:
        evidence = draft.evidence_index.get(source_id)
        if evidence is not None and evidence.subject:
            by_subject.setdefault(evidence.subject, []).append(evidence)
    if len(by_subject) < 2:
        aggregate = [draft.evidence_index[source_id] for source_id in task.fact_ids if source_id in draft.evidence_index and draft.evidence_index[source_id].kind == "performance_comparison"]
        if aggregate:
            return (["**可比表现**", *[f"{_fact_text(evidence, 'comparison')} {refs([evidence.source_id])}" for evidence in aggregate], "历史区间的表现差异不代表未来收益或风险。"], {evidence.source_id for evidence in aggregate})
        return (["[数据缺失] 尚未取得至少两个对象的可比事实，不能完成横向判断。"], set())
    subjects = list(by_subject)
    kinds = list(dict.fromkeys(item.kind for items in by_subject.values() for item in items))
    lines = ["**横向证据比较**", "", "| 维度 | " + " | ".join(subjects) + " |", "| --- | " + " | ".join("---" for _ in subjects) + " |"]
    for kind in kinds:
        cells = []
        for subject in subjects:
            items = [item for item in by_subject[subject] if item.kind == kind]
            texts = [f"{_fact_text(item, 'comparison')} {refs([item.source_id])}" for item in items]
            used_sources.update(item.source_id for item in items)
            cell = "；".join(texts) if texts else "[数据缺失]"
            cells.append(cell.replace("|", "/").replace("\n", " "))
        lines.append("| " + _KIND_LABELS.get(kind, "证据") + " | " + " | ".join(cells) + " |")
    metrics = (("forwardPE", "Forward P/E"), ("trailingPE", "Trailing P/E"), ("profitMargins", "利润率"), ("revenueGrowth", "营收增长率"))
    if len(subjects) == 2:
        for key, label in metrics:
            values = []
            selected = []
            for subject in subjects:
                item = next((item for item in by_subject[subject] if isinstance(item.structured_data.get(key), (int, float))), None)
                selected.append(item)
                values.append(item.structured_data[key] if item is not None else None)
            if all(value is not None for value in values) and values[0] != values[1]:
                periods = [item.period_end or item.as_of for item in selected]
                if not all(periods) or periods[0] != periods[1] or selected[0].unit != selected[1].unit or selected[0].frequency != selected[1].frequency:
                    lines.append(f"- {label} 的源数据时间或口径尚未对齐，不能据此形成同口径高低判断。")
                    continue
                higher = subjects[0] if values[0] > values[1] else subjects[1]
                lines.append(f"- 按本轮源数据，{higher} 的 {label} 较高（{subjects[0]} {_value(values[0])}；{subjects[1]} {_value(values[1])}）。")
    lines.append("估值、盈利与风险需要共同评估；以上事实差异本身不构成买入或卖出建议。")
    return lines, used_sources


def render_research_report(
    draft: ReportSynthesisDraft,
    *,
    output_mode: str = "investment_report",
    direction_readiness: dict[str, Any] | None = None,
    allow_overall_conclusion: bool = True,
) -> ResearchReportRenderResult:
    profile = output_mode if output_mode in {"chat", "brief"} else "full"
    reference_numbers = {}
    reference_identities = {}
    reference_ids = list(dict.fromkeys([*draft.citation_ids, *(
        source_id for source_id, evidence in draft.evidence_index.items()
        if evidence.metadata.get("verification") == "discovery_only"
    )]))
    for source_id in reference_ids:
        evidence = draft.evidence_index.get(source_id)
        if evidence is None:
            continue
        identity = (canonical_news_url(evidence.url), evidence.as_of) if evidence.url else (_source_label(evidence), None)
        if identity not in reference_identities:
            reference_identities[identity] = str(len(reference_identities) + 1)
        reference_numbers[source_id] = reference_identities[identity]

    def refs(source_ids: list[str]) -> str:
        numbers = dict.fromkeys(reference_numbers[source_id] for source_id in source_ids if source_id in reference_numbers)
        return " ".join(f"[{value}]" for value in numbers)

    lines = []
    blocked_direction = any(_requires_investment_direction(task) and isinstance((direction_readiness or {}).get(task.task_id), dict) and not direction_readiness[task.task_id].get("direction_allowed") for task in draft.task_results)
    overall_has_direction = bool(re.search(r"偏多|偏空|\b(?:bullish|bearish|buy|sell|hold)\b|(?:方向|建议|评级).{0,12}(?:中性|买入|卖出|持有)", draft.overall_conclusion or "", re.IGNORECASE))
    rendered_task_ids: list[str] = []
    shown_sources: set[str] = set()
    shown_materials: set[tuple[str | None, str, str | None]] = set()
    for task in draft.task_results:
        rendered_task_ids.append(task.task_id)
        readiness = (direction_readiness or {}).get(task.task_id)
        direction_requested = _requires_investment_direction(task)
        direction_allowed = not direction_requested or not isinstance(readiness, dict) or bool(readiness.get("direction_allowed"))
        comparison_task = task.render_kind == "compare" or task.operation == "compare"
        display_fact_ids = select_fact_ids(draft, task, profile)
        display_claims = select_claims(draft, task, profile, direction_allowed=direction_allowed)
        for check in task.requirement_results:
            if check.get("status") != "answered":
                continue
            for source_id in check.get("evidence_ids") or []:
                if source_id in task.fact_ids and source_id not in display_fact_ids:
                    display_fact_ids.append(source_id)
            for claim_id in check.get("claim_ids") or []:
                claim = draft.claim_index.get(claim_id)
                if claim is not None and claim_id in task.claim_ids and (direction_allowed or not claim.directional) and claim not in display_claims:
                    display_claims.append(claim)
        display_claims = [claim for claim in display_claims if claim_has_reliable_sources(claim, task, draft.evidence_index)]
        comparison, comparison_sources = _comparison_lines(draft, task, refs) if comparison_task else ([], set())
        if task.answer_requirements:
            subjects = task.requested_subjects or list(dict.fromkeys(draft.evidence_index[source_id].subject for source_id in task.fact_ids if source_id in draft.evidence_index and draft.evidence_index[source_id].subject))
            evaluate_answer_requirements(
                result=task, requirements=task.answer_requirements, evidence_index=draft.evidence_index,
                claim_index=draft.claim_index, subjects=subjects,
                displayed_evidence_ids=list(comparison_sources) if comparison_task else display_fact_ids,
                displayed_claim_ids=[claim.claim_id for claim in display_claims],
            )
        display_status = "partial" if task.status == "answered" and (task.fallback_used or task.missing_evidence or task.missing_requirements) else task.status
        lines.extend([f"## {task.title} · {_STATUS_LABEL[display_status]}", ""])
        if direction_requested and isinstance(readiness, dict) and not direction_allowed:
            lines.extend(["当前证据不足以形成统一方向判断，以下保留已验证事实与风险。", ""])
        shown_task_claims = set()
        if comparison_task:
            lines.extend(comparison)
            shown_sources.update(comparison_sources)
            lines.append("")
        for dimension, label, kinds in (
            ("business_model", "业务与商业模式", {"company_profile", "filing_context", "document_context"}),
            ("competition", "竞争格局", {"company_profile", "news_context", "document_context"}),
        ):
            if comparison_task or dimension not in task.requested_dimensions:
                continue
            materials = [draft.evidence_index[source_id] for source_id in display_fact_ids if source_id in draft.evidence_index and draft.evidence_index[source_id].kind in kinds]
            explanations = [
                claim for claim in display_claims
                if claim.agent_name == "research_analyst" and (
                    claim.metric == dimension or (claim.metric is None and any(
                        draft.evidence_index[source_id].metric == dimension
                        or draft.evidence_index[source_id].metadata.get("dimension") == dimension
                        for source_id in claim.evidence_ids if source_id in draft.evidence_index
                    ))
                )
            ]
            lines.extend([f"**{label}**", ""])
            if explanations:
                fresh = [claim for claim in explanations if claim.claim_id not in shown_task_claims]
                if fresh:
                    lines.extend(f"- {_line(claim.text)} {refs(claim.evidence_ids)}" for claim in fresh)
                    shown_sources.update(source_id for claim in fresh for source_id in claim.evidence_ids)
                    shown_task_claims.update(claim.claim_id for claim in fresh)
                else:
                    lines.append("对应解释已纳入上方研究判断。")
            elif materials:
                lines.append("[数据缺失] 已取得相关材料，但本轮尚未形成通过引用校验的对应解释。")
            else:
                lines.append(f"[数据缺失] 未取得可验证的{label}材料，不能补造结论。")
            lines.append("")
        facts_by_kind = {}
        for source_id in [] if comparison_task else display_fact_ids:
            evidence = draft.evidence_index.get(source_id)
            if evidence is not None and evidence.usage == "fact" and task.task_id in evidence.task_ids:
                facts_by_kind.setdefault(evidence.kind, []).append(evidence)
        displayed_rows = set()
        for kind, items in facts_by_kind.items():
            fact_lines = []
            displayed_facts = set()
            for evidence in items:
                text = _fact_text(evidence, profile)
                material_identity = (evidence.subject, text, evidence.url)
                if evidence.kind in {"filing_context", "document_context", "transcript_context"} and material_identity in shown_materials:
                    shown_sources.add(evidence.source_id)
                    continue
                if text and (evidence.subject, text) not in displayed_facts:
                    displayed_facts.add((evidence.subject, text))
                    prefix = f"{evidence.subject}：" if task.render_kind == "compare" and evidence.subject and not text.startswith(evidence.subject) else ""
                    rows = [row for row in text.splitlines() if (evidence.subject, row) not in displayed_rows]
                    if not rows:
                        continue
                    displayed_rows.update((evidence.subject, row) for row in rows)
                    fact_lines.append(f"- {prefix}{rows[0]} {refs([evidence.source_id])}".rstrip())
                    fact_lines.extend(f"  - {row}" for row in rows[1:])
                    shown_sources.add(evidence.source_id)
                    shown_materials.add(material_identity)
            if fact_lines:
                lines.extend([f"**{_KIND_LABELS.get(kind, '已验证事实')}**", "", *fact_lines, ""])
        selected_claims = [claim for claim in display_claims if claim.claim_id not in shown_task_claims]
        if selected_claims:
            lines.extend(["**研究判断与风险**", ""])
            for claim in selected_claims:
                lines.append(f"- {_line(claim.text)} {refs(claim.evidence_ids)}".rstrip())
                shown_sources.update(claim.evidence_ids)
            lines.append("")
        if not facts_by_kind and not selected_claims and not comparison_task and not shown_task_claims:
            lines.append("[数据缺失] 本轮没有取得可验证的对应事实或论据。")
        for dimension in task.requested_dimensions:
            kinds = DIMENSION_KINDS.get(dimension)
            if kinds and not any(claim.metric == dimension for claim in display_claims) and not any(draft.evidence_index[source_id].kind in kinds for source_id in display_fact_ids if source_id in draft.evidence_index):
                label = _DIMENSION_LABELS.get(dimension, "请求维度")
                if task.operation == "macro_brief" and dimension == "performance":
                    continue
                lines.append(f"- [数据缺失] {label}尚无可展示的已验证事实。")
        claimed_sources = {source_id for claim in display_claims for source_id in claim.evidence_ids}
        discovery = [evidence for evidence in draft.evidence_index.values() if task.task_id in evidence.task_ids and evidence.metadata.get("verification") == "discovery_only" and evidence.source_id not in claimed_sources]
        if discovery:
            lines.extend(["", "**未核实的检索材料**"])
            lines.append("部分材料的来源、发布日期或内容尚未核实，未纳入上述结论。")
        covered_missing = {missing.get("evidence_kind") for missing in task.missing_requirements}
        for kind in task.missing_evidence:
            if kind in covered_missing:
                continue
            lines.append(f"- [数据缺失] {_KIND_LABELS.get(kind, '必要证据')}尚未满足。")
        for missing in task.missing_requirements:
            if missing.get("description"):
                lines.append(f"- [未完成] {_requirement_gap_text(missing)}。")
                continue
            label = _KIND_LABELS.get(missing.get("evidence_kind"), "必要证据")
            subject = str(missing.get("subject") or task.subject or "对应对象")
            lines.append(f"- [数据缺失] {subject} 的{label}尚未满足。")
        for limitation in task.limitations:
            if limitation not in draft.limitations:
                lines.append(f"- {_line(limitation)}")
        lines.append("")
    draft.status = aggregate_task_status([task.status for task in draft.task_results])
    overall_reasons = overall_conclusion_block_reasons(draft)
    if not allow_overall_conclusion:
        overall_reasons.append("report_quality_blocked")
    if blocked_direction and overall_has_direction:
        overall_reasons.append("investment_direction_unavailable")
    removed_overall = bool(overall_reasons and draft.overall_conclusion)
    if removed_overall:
        draft.overall_conclusion = None
    if removed_overall or "overall_block_reasons" in draft.synthesis_validation:
        draft.synthesis_validation = {**draft.synthesis_validation, "overall_block_reasons": list(dict.fromkeys(overall_reasons))}
    if profile == "full":
        overall_text = _public_text(draft.overall_conclusion) if draft.overall_conclusion else "无法判断：本轮尚未形成证据支持的完整总体结论。"
        lines = ["## 总判断", "", overall_text, "", *lines]
    disclosures = list(draft.risks) if profile == "full" else list(dict.fromkeys(draft.risks))[:2 if profile == "brief" else 3]
    for conflict in draft.conflicts:
        if conflict.material:
            claims = [draft.claim_index.get(claim_id) for claim_id in conflict.claim_ids]
            texts = [claim.text for claim in claims if claim is not None]
            if len(texts) == 2:
                disclosures.append("同一对象、指标、期限和情景存在未解决分歧：" + "；".join(texts))
    if disclosures:
        lines.extend(["## 风险与分歧", "", *[f"- {_line(item)}" for item in dict.fromkeys(disclosures)], ""])
    if draft.limitations:
        limitations = list(dict.fromkeys(draft.limitations))
        if profile != "full":
            essential = [value for value in limitations if re.search(r"模型|校验|缺失|未核实|未提供|原生论据", value)]
            limitations = list(dict.fromkeys(essential + limitations))[:2 if profile == "brief" else 3]
        lines.extend(["## 限制", "", *[f"- {_line(item)}" for item in limitations], ""])
    if any(source_id in reference_numbers for source_id in shown_sources):
        lines.extend(["## 来源", ""])
    shown_reference_labels = set()
    for source_id in reference_ids:
        if source_id not in shown_sources or source_id not in reference_numbers:
            continue
        evidence = draft.evidence_index[source_id]
        label = _source_label(evidence)
        number = reference_numbers[source_id]
        identity = number
        if identity in shown_reference_labels:
            continue
        shown_reference_labels.add(identity)
        if evidence.url:
            lines.append(f"- [{number}] [{_line(label)}]({evidence.url})")
        else:
            lines.append(f"- [{number}] {_line(label)}")
    draft.status = aggregate_task_status([task.status for task in draft.task_results])
    return ResearchReportRenderResult(
        markdown="\n".join(lines).strip() + "\n",
        rendered_task_ids=rendered_task_ids,
        citation_ids=[source_id for source_id in reference_ids if source_id in shown_sources and source_id in reference_numbers],
        citation_numbers={source_id: reference_numbers[source_id] for source_id in reference_ids if source_id in shown_sources and source_id in reference_numbers},
    )


__all__ = ["render_research_report"]
