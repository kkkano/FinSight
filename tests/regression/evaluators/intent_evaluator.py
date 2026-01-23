# -*- coding: utf-8 -*-
"""
Intent Evaluator - 验证意图分类是否正确
"""
from typing import Any, Dict
from .base import BaseEvaluator, EvalResult


class IntentEvaluator(BaseEvaluator):
    """Evaluate intent classification accuracy"""

    def evaluate(self, result: Any, expected: Dict[str, Any]) -> EvalResult:
        expected_intent = expected.get("intent", "").lower()
        if not expected_intent:
            return EvalResult(passed=True, score=1.0, details={"skipped": "no expected intent"})

        actual_intent = ""
        if hasattr(result, "intent"):
            actual_intent = result.intent.value if hasattr(result.intent, "value") else str(result.intent)
        actual_intent = actual_intent.lower()

        passed = actual_intent == expected_intent
        return EvalResult(
            passed=passed,
            score=1.0 if passed else 0.0,
            details={
                "expected_intent": expected_intent,
                "actual_intent": actual_intent
            },
            errors=[] if passed else [f"Intent mismatch: expected '{expected_intent}', got '{actual_intent}'"]
        )
