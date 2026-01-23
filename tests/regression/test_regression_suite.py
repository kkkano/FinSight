# -*- coding: utf-8 -*-
"""
FinSight Regression Test Suite
主测试入口 - 使用 Mock 数据源，不依赖外网
"""
import json
import os
import sys
import time
import pytest
from typing import Dict, Any, List

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

BASELINES_DIR = os.path.join(os.path.dirname(__file__), "baselines")


def load_baseline_cases() -> List[Dict[str, Any]]:
    path = os.path.join(BASELINES_DIR, "baseline_cases.json")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("cases", [])


class TestRegressionSuite:
    """Regression test suite for SupervisorAgent"""

    @pytest.fixture(autouse=True)
    def setup(self, supervisor, evaluators):
        self.supervisor = supervisor
        self.evaluators = evaluators

    @pytest.mark.asyncio
    @pytest.mark.parametrize("case", load_baseline_cases(), ids=lambda c: c.get("id", "unknown"))
    async def test_baseline_case(self, case: Dict[str, Any]):
        """Run a single baseline test case"""
        if case.get("skip", False):
            pytest.skip(f"Case {case['id']} is marked as skip")

        case_id = case.get("id", "unknown")
        input_data = case.get("input", {})
        expected = case.get("expected", {})
        timeout_ms = case.get("timeout_ms", 5000)

        query = input_data.get("query", "")
        tickers = input_data.get("tickers", [])
        context_summary = input_data.get("context_summary")

        # Execute
        start_time = time.time()
        try:
            result = await self.supervisor.process(
                query=query,
                tickers=tickers,
                context_summary=context_summary
            )
        except Exception as e:
            pytest.fail(f"Case {case_id} raised exception: {e}")

        duration_ms = (time.time() - start_time) * 1000

        # Evaluate
        errors = []

        # 1. Intent evaluation
        intent_result = self.evaluators["intent"].evaluate(result, expected)
        if not intent_result.passed:
            errors.extend(intent_result.errors)

        # 2. Success evaluation
        expected_success = expected.get("success", True)
        actual_success = result.success if hasattr(result, "success") else True
        if expected_success != actual_success:
            errors.append(f"Success mismatch: expected {expected_success}, got {actual_success}")

        # 3. Structure evaluation (for report intent)
        if expected.get("sections"):
            structure_result = self.evaluators["structure"].evaluate(result, expected)
            if not structure_result.passed:
                errors.extend(structure_result.errors)

        # 4. Citation evaluation
        if expected.get("min_citations", 0) > 0:
            citation_result = self.evaluators["citation"].evaluate(result, expected)
            if not citation_result.passed:
                errors.extend(citation_result.errors)

        # 5. Response contains check
        response_contains = expected.get("response_contains", [])
        response_text = result.response if hasattr(result, "response") else ""
        for keyword in response_contains:
            if keyword.lower() not in response_text.lower():
                errors.append(f"Response missing keyword: '{keyword}'")

        # 6. Timeout check
        if duration_ms > timeout_ms:
            errors.append(f"Timeout: {duration_ms:.0f}ms > {timeout_ms}ms")

        # Assert
        assert len(errors) == 0, f"Case {case_id} failed:\n" + "\n".join(errors)


# Quick smoke test for import validation
def test_imports():
    """Verify all imports work correctly"""
    from tests.regression.mocks import MockToolsModule, MockLLM
    from tests.regression.evaluators import IntentEvaluator, StructureEvaluator, CitationEvaluator
    assert MockToolsModule is not None
    assert MockLLM is not None
    assert IntentEvaluator is not None
