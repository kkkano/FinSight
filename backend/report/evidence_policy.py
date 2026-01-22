# -*- coding: utf-8 -*-
"""
EvidencePolicy - 证据覆盖率与引用校验。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set

from backend.report.ir import ReportIR, ReportSection, ReportContent


KEY_SECTION_KEYWORDS = (
    "summary",
    "executive",
    "conclusion",
    "recommendation",
    "risk",
    "结论",
    "摘要",
    "建议",
    "风险",
    "投资策略",
)


@dataclass
class EvidencePolicyResult:
    coverage: float
    total_blocks: int
    covered_blocks: int
    unique_sources: int
    invalid_refs: List[str]
    key_section_issues: List[str]
    meets_coverage: bool
    meets_min_sources: bool


class EvidencePolicy:
    DEFAULT_MIN_COVERAGE = 0.8
    DEFAULT_MIN_SOURCES = 2
    DEFAULT_MIN_KEY_SECTION_SOURCES = 2

    @staticmethod
    def _iter_sections(sections: Iterable[ReportSection]) -> Iterable[ReportSection]:
        for section in sections:
            yield section
            if section.subsections:
                for sub in EvidencePolicy._iter_sections(section.subsections):
                    yield sub

    @staticmethod
    def _iter_contents(sections: Iterable[ReportSection]) -> Iterable[ReportContent]:
        for section in EvidencePolicy._iter_sections(sections):
            for content in section.contents:
                yield content

    @staticmethod
    def _is_key_section(title: str) -> bool:
        lower = title.lower()
        return any(keyword in lower for keyword in KEY_SECTION_KEYWORDS)

    @staticmethod
    def apply(
        report: ReportIR,
        min_coverage: float = DEFAULT_MIN_COVERAGE,
        min_sources: int = DEFAULT_MIN_SOURCES,
        min_key_section_sources: int = DEFAULT_MIN_KEY_SECTION_SOURCES,
    ) -> EvidencePolicyResult:
        if not isinstance(report.meta, dict):
            report.meta = {}

        valid_ids: Set[str] = set()
        for citation in report.citations or []:
            if citation.source_id:
                valid_ids.add(citation.source_id)

        total_blocks = 0
        covered_blocks = 0
        invalid_refs: List[str] = []
        used_refs: Set[str] = set()

        for content in EvidencePolicy._iter_contents(report.sections):
            total_blocks += 1
            refs = content.citation_refs or []
            if refs:
                valid_refs = [ref for ref in refs if ref in valid_ids]
                invalid_refs.extend([ref for ref in refs if ref not in valid_ids])
                content.citation_refs = valid_refs
                if valid_refs:
                    covered_blocks += 1
                    used_refs.update(valid_refs)
            else:
                content.citation_refs = []

        coverage = covered_blocks / total_blocks if total_blocks > 0 else 0.0

        key_section_issues: List[str] = []
        for section in EvidencePolicy._iter_sections(report.sections):
            if not EvidencePolicy._is_key_section(section.title):
                continue
            section_refs: Set[str] = set()
            for content in section.contents:
                section_refs.update(content.citation_refs or [])
            if len(section_refs) < min_key_section_sources:
                key_section_issues.append(
                    f"{section.title} refs<{min_key_section_sources}"
                )

        meets_coverage = coverage >= min_coverage
        meets_min_sources = len(used_refs) >= min_sources

        status = "pass" if (meets_coverage and meets_min_sources and not key_section_issues) else "warning"
        report.meta["evidence_policy"] = {
            "status": status,
            "coverage": round(coverage, 4),
            "covered_blocks": covered_blocks,
            "total_blocks": total_blocks,
            "unique_sources": len(used_refs),
            "min_coverage": min_coverage,
            "min_sources": min_sources,
            "min_key_section_sources": min_key_section_sources,
            "invalid_refs": sorted(set(invalid_refs)),
            "key_section_issues": key_section_issues,
            "meets_coverage": meets_coverage,
            "meets_min_sources": meets_min_sources,
        }

        if status != "pass":
            risk_message = "证据覆盖率或引用数量不足，结论可信度下降，请谨慎参考。"
            if risk_message not in report.risks:
                report.risks.append(risk_message)

        return EvidencePolicyResult(
            coverage=coverage,
            total_blocks=total_blocks,
            covered_blocks=covered_blocks,
            unique_sources=len(used_refs),
            invalid_refs=sorted(set(invalid_refs)),
            key_section_issues=key_section_issues,
            meets_coverage=meets_coverage,
            meets_min_sources=meets_min_sources,
        )
