# -*- coding: utf-8 -*-
"""ResearchSynthesisDraft 的唯一 Markdown renderer。"""
from __future__ import annotations

from backend.graph.synthesis.contracts import ReportSynthesisDraft, ResearchReportRenderResult

_STATUS_LABEL = {
    "answered": "已回答",
    "partial": "部分完成",
    "unavailable": "暂不可用",
    "blocked": "需要补充信息",
}


def _line(value: str) -> str:
    return " ".join(value.split())


def render_research_report(draft: ReportSynthesisDraft) -> ResearchReportRenderResult:
    lines = ["## 总判断", "", draft.overall_conclusion or "当前证据不足，无法形成总判断。", ""]

    lines.extend(["## 分任务结论", ""])
    rendered_task_ids: list[str] = []
    for task in draft.task_results:
        rendered_task_ids.append(task.task_id)
        lines.extend([
            f"### {task.title}", "",
            f"- 状态：{_STATUS_LABEL[task.status]}",
            f"- 结论：{_line(task.conclusion) if task.conclusion else '当前没有足够的受支持结论。'}",
            "",
        ])

    lines.extend(["## 关键论据与证据", ""])
    shown_claims: set[str] = set()
    for task in draft.task_results:
        for claim_id in task.claim_ids:
            if claim_id in shown_claims:
                continue
            claim = draft.claim_index[claim_id]
            refs = " ".join(f"[{source_id}]" for source_id in claim.evidence_ids)
            lines.append(f"- `{claim.claim_id}` [{claim.agent_name}] {_line(claim.text)} {refs}".rstrip())
            shown_claims.add(claim_id)
    if not shown_claims:
        lines.append("- 暂无通过校验的结构化论据。")
    lines.append("")

    lines.extend(["## 分歧与风险", ""])
    disclosures: list[str] = []
    disclosures.extend(draft.disagreements)
    disclosures.extend(draft.risks)
    for conflict in draft.conflicts:
        disclosures.append(f"未解决冲突 `{conflict.conflict_id}`：{' / '.join(conflict.claim_ids)}")
    lines.extend([f"- {_line(item)}" for item in disclosures] or ["- 暂无额外分歧或风险披露。"])
    lines.append("")

    lines.extend(["## 限制", ""])
    lines.extend([f"- {_line(item)}" for item in draft.limitations] or ["- 暂无额外限制。"])
    lines.append("")

    lines.extend(["## 引用", ""])
    for source_id in draft.citation_ids:
        evidence = draft.evidence_index[source_id]
        label = evidence.title or evidence.source_name or evidence.text
        if evidence.url:
            lines.append(f"- [{source_id}] [{_line(label)}]({evidence.url})")
        else:
            lines.append(f"- [{source_id}] {_line(label)}")
    if not draft.citation_ids:
        lines.append("- 暂无可展示引用。")

    return ResearchReportRenderResult(
        markdown="\n".join(lines).strip() + "\n",
        rendered_task_ids=rendered_task_ids,
    )


__all__ = ["render_research_report"]
