# -*- coding: utf-8 -*-
"""
Base evaluator and result dataclass
"""
from dataclasses import dataclass, field
from typing import Dict, List, Any


@dataclass
class EvalResult:
    """Evaluation result for a single test case"""
    passed: bool
    score: float  # 0.0 - 1.0
    details: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "score": self.score,
            "details": self.details,
            "errors": self.errors
        }


class BaseEvaluator:
    """Base class for evaluators"""

    def evaluate(self, result: Any, expected: Dict[str, Any]) -> EvalResult:
        raise NotImplementedError
