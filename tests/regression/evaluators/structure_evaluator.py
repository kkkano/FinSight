# -*- coding: utf-8 -*-
"""
Structure Evaluator - 验证报告结构是否包含期望章节
"""
from typing import Any, Dict, List
from .base import BaseEvaluator, EvalResult


class StructureEvaluator(BaseEvaluator):
    """Evaluate report structure coverage"""

    def evaluate(self, result: Any, expected: Dict[str, Any]) -> EvalResult:
        expected_sections = expected.get("sections", [])
        if not expected_sections:
            return EvalResult(passed=True, score=1.0, details={"skipped": "no expected sections"})

        # Extract actual sections from result
        actual_sections = []
        if hasattr(result, "forum_output") and result.forum_output:
            consensus = getattr(result.forum_output, "consensus", "")
            actual_sections = self._extract_sections(consensus)
        elif hasattr(result, "response"):
            actual_sections = self._extract_sections(result.response)

        # Check coverage
        matched = []
        missing = []
        for section in expected_sections:
            found = any(section.lower() in s.lower() for s in actual_sections)
            if found:
                matched.append(section)
            else:
                missing.append(section)

        coverage = len(matched) / len(expected_sections) if expected_sections else 1.0
        passed = coverage >= 0.8  # 80% threshold

        return EvalResult(
            passed=passed,
            score=coverage,
            details={
                "expected_sections": expected_sections,
                "matched_sections": matched,
                "missing_sections": missing,
                "coverage": coverage
            },
            errors=[] if passed else [f"Structure coverage {coverage:.0%} < 80%: missing {missing}"]
        )

    def _extract_sections(self, text: str) -> List[str]:
        """Extract section titles from text"""
        sections = []
        for line in text.split("\n"):
            line = line.strip()
            if line.startswith("###") or line.startswith("##"):
                title = line.lstrip("#").strip()
                sections.append(title)
        return sections
