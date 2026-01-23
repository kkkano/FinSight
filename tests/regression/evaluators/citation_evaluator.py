# -*- coding: utf-8 -*-
"""
Citation Evaluator - 验证引用数量是否达标
"""
from typing import Any, Dict
from .base import BaseEvaluator, EvalResult


class CitationEvaluator(BaseEvaluator):
    """Evaluate citation count compliance"""

    def evaluate(self, result: Any, expected: Dict[str, Any]) -> EvalResult:
        min_citations = expected.get("min_citations", 0)
        if min_citations == 0:
            return EvalResult(passed=True, score=1.0, details={"skipped": "no citation requirement"})

        # Count actual citations
        actual_count = 0
        if hasattr(result, "agent_outputs") and result.agent_outputs:
            for agent_name, output in result.agent_outputs.items():
                if hasattr(output, "evidence") and output.evidence:
                    actual_count += len(output.evidence)

        passed = actual_count >= min_citations
        score = min(1.0, actual_count / min_citations) if min_citations > 0 else 1.0

        return EvalResult(
            passed=passed,
            score=score,
            details={
                "min_citations": min_citations,
                "actual_citations": actual_count
            },
            errors=[] if passed else [f"Citation count {actual_count} < required {min_citations}"]
        )
