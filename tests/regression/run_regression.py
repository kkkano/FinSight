#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
FinSight Regression Test Runner
一键运行脚本 - 输出 JSON/Markdown 对比报告

Usage:
    python tests/regression/run_regression.py
    python tests/regression/run_regression.py --output reports/
    python tests/regression/run_regression.py --category report
"""
import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from typing import Dict, Any, List
from dataclasses import dataclass, field, asdict

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from tests.regression.mocks.mock_tools import MockToolsModule
from tests.regression.mocks.mock_llm import MockLLM
from tests.regression.evaluators.intent_evaluator import IntentEvaluator
from tests.regression.evaluators.structure_evaluator import StructureEvaluator
from tests.regression.evaluators.citation_evaluator import CitationEvaluator

BASELINES_DIR = os.path.join(os.path.dirname(__file__), "baselines")
REPORTS_DIR = os.path.join(os.path.dirname(__file__), "reports")


@dataclass
class CaseResult:
    case_id: str
    name: str
    category: str
    passed: bool
    duration_ms: float
    intent_match: bool
    structure_coverage: float
    citation_count: int
    errors: List[str] = field(default_factory=list)


@dataclass
class RegressionReport:
    run_id: str
    timestamp: str
    duration_seconds: float
    total: int
    passed: int
    failed: int
    skipped: int
    pass_rate: float
    metrics: Dict[str, float] = field(default_factory=dict)
    cases: List[Dict] = field(default_factory=list)
    failures: List[Dict] = field(default_factory=list)


def load_baseline_cases(category: str = None) -> List[Dict]:
    path = os.path.join(BASELINES_DIR, "baseline_cases.json")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    cases = data.get("cases", [])
    if category:
        cases = [c for c in cases if c.get("category") == category]
    return cases


async def run_single_case(supervisor, evaluators, case: Dict) -> CaseResult:
    case_id = case.get("id", "unknown")
    name = case.get("name", "")
    category = case.get("category", "")
    input_data = case.get("input", {})
    expected = case.get("expected", {})

    query = input_data.get("query", "")
    tickers = input_data.get("tickers", [])
    context_summary = input_data.get("context_summary")

    errors = []
    intent_match = False
    structure_coverage = 0.0
    citation_count = 0

    start_time = time.time()
    try:
        result = await supervisor.process(
            query=query,
            tickers=tickers,
            context_summary=context_summary
        )
        duration_ms = (time.time() - start_time) * 1000

        # Evaluate intent
        intent_result = evaluators["intent"].evaluate(result, expected)
        intent_match = intent_result.passed
        if not intent_match:
            errors.extend(intent_result.errors)

        # Evaluate success
        expected_success = expected.get("success", True)
        actual_success = result.success if hasattr(result, "success") else True
        if expected_success != actual_success:
            errors.append(f"Success mismatch: expected {expected_success}, got {actual_success}")

        # Evaluate structure
        if expected.get("sections"):
            structure_result = evaluators["structure"].evaluate(result, expected)
            structure_coverage = structure_result.score
            if not structure_result.passed:
                errors.extend(structure_result.errors)

        # Evaluate citations
        citation_result = evaluators["citation"].evaluate(result, expected)
        citation_count = citation_result.details.get("actual_citations", 0)
        if not citation_result.passed:
            errors.extend(citation_result.errors)

        # Check response contains
        response_contains = expected.get("response_contains", [])
        response_text = result.response if hasattr(result, "response") else ""
        for keyword in response_contains:
            if keyword.lower() not in response_text.lower():
                errors.append(f"Response missing keyword: '{keyword}'")

    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        errors.append(f"Exception: {str(e)}")

    passed = len(errors) == 0
    return CaseResult(
        case_id=case_id,
        name=name,
        category=category,
        passed=passed,
        duration_ms=duration_ms,
        intent_match=intent_match,
        structure_coverage=structure_coverage,
        citation_count=citation_count,
        errors=errors
    )


async def run_regression(category: str = None) -> RegressionReport:
    """Run all regression tests and return report"""
    run_id = f"reg-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    timestamp = datetime.now().isoformat()

    # Initialize mock environment
    mock_tools = MockToolsModule()
    mock_llm = MockLLM()

    from backend.orchestration.cache import DataCache
    from backend.services.circuit_breaker import CircuitBreaker
    from backend.orchestration.supervisor_agent import SupervisorAgent

    supervisor = SupervisorAgent(
        llm=mock_llm,
        tools_module=mock_tools,
        cache=DataCache(),
        circuit_breaker=CircuitBreaker()
    )

    evaluators = {
        "intent": IntentEvaluator(),
        "structure": StructureEvaluator(),
        "citation": CitationEvaluator()
    }

    # Load cases
    cases = load_baseline_cases(category)
    total = len(cases)
    skipped = sum(1 for c in cases if c.get("skip", False))

    # Run tests
    start_time = time.time()
    results: List[CaseResult] = []

    for case in cases:
        if case.get("skip", False):
            continue
        result = await run_single_case(supervisor, evaluators, case)
        results.append(result)
        status = "[PASS]" if result.passed else "[FAIL]"
        print(f"  {status} {result.case_id}: {result.name} ({result.duration_ms:.0f}ms)")

    duration_seconds = time.time() - start_time

    # Calculate metrics
    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed
    pass_rate = passed / len(results) if results else 0

    intent_accuracy = sum(1 for r in results if r.intent_match) / len(results) if results else 0
    avg_duration = sum(r.duration_ms for r in results) / len(results) if results else 0
    durations = sorted([r.duration_ms for r in results])
    p95_duration = durations[int(len(durations) * 0.95)] if durations else 0

    total_citations = sum(r.citation_count for r in results)
    avg_structure_coverage = sum(r.structure_coverage for r in results) / len(results) if results else 0

    # Build report
    report = RegressionReport(
        run_id=run_id,
        timestamp=timestamp,
        duration_seconds=duration_seconds,
        total=total,
        passed=passed,
        failed=failed,
        skipped=skipped,
        pass_rate=pass_rate,
        metrics={
            "intent_accuracy": intent_accuracy,
            "avg_duration_ms": avg_duration,
            "p95_duration_ms": p95_duration,
            "total_citations": total_citations,
            "avg_structure_coverage": avg_structure_coverage
        },
        cases=[asdict(r) for r in results],
        failures=[asdict(r) for r in results if not r.passed]
    )

    return report


def save_json_report(report: RegressionReport, output_dir: str):
    os.makedirs(output_dir, exist_ok=True)
    filename = f"regression_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    path = os.path.join(output_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(report), f, indent=2, ensure_ascii=False)
    print(f"\n[JSON] Report saved: {path}")
    return path


def save_markdown_report(report: RegressionReport, output_dir: str):
    os.makedirs(output_dir, exist_ok=True)
    filename = f"regression_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    path = os.path.join(output_dir, filename)

    lines = [
        "# FinSight 回归测试报告",
        "",
        f"**运行时间**: {report.timestamp}",
        f"**总耗时**: {report.duration_seconds:.1f}s",
        f"**通过率**: {report.pass_rate:.0%} ({report.passed}/{report.total})",
        "",
        "## 指标概览",
        "",
        "| 指标 | 值 | 阈值 | 状态 |",
        "|------|-----|------|------|",
        f"| 意图准确率 | {report.metrics['intent_accuracy']:.0%} | >=95% | {'PASS' if report.metrics['intent_accuracy'] >= 0.95 else 'FAIL'} |",
        f"| 平均耗时 | {report.metrics['avg_duration_ms']:.0f}ms | <3000ms | {'PASS' if report.metrics['avg_duration_ms'] < 3000 else 'FAIL'} |",
        f"| P95 耗时 | {report.metrics['p95_duration_ms']:.0f}ms | <10000ms | {'PASS' if report.metrics['p95_duration_ms'] < 10000 else 'FAIL'} |",
        f"| 总引用数 | {report.metrics['total_citations']} | - | - |",
        "",
    ]

    if report.failures:
        lines.extend([
            "## 失败用例",
            "",
        ])
        for f in report.failures:
            lines.append(f"### {f['case_id']}: {f['name']}")
            lines.append(f"- **类别**: {f['category']}")
            lines.append(f"- **耗时**: {f['duration_ms']:.0f}ms")
            lines.append(f"- **错误**: {'; '.join(f['errors'])}")
            lines.append("")

    lines.extend([
        "## 详细结果",
        "",
        "| ID | 名称 | 类别 | 状态 | 耗时 |",
        "|-----|------|------|------|------|",
    ])
    for c in report.cases:
        status = "PASS" if c["passed"] else "FAIL"
        lines.append(f"| {c['case_id']} | {c['name']} | {c['category']} | {status} | {c['duration_ms']:.0f}ms |")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[MD] Report saved: {path}")
    return path


def main():
    parser = argparse.ArgumentParser(description="FinSight Regression Test Runner")
    parser.add_argument("--output", "-o", default=REPORTS_DIR, help="Output directory for reports")
    parser.add_argument("--category", "-c", help="Only run tests in this category")
    parser.add_argument("--format", "-f", default="json,md", help="Output formats (json,md)")
    args = parser.parse_args()

    print("=" * 60)
    print("[TEST] FinSight Regression Test Suite")
    print("=" * 60)
    print()

    report = asyncio.run(run_regression(args.category))

    print()
    print("=" * 60)
    print(f"[RESULT] {report.passed}/{report.total} passed ({report.pass_rate:.0%})")
    print(f"[TIME] Duration: {report.duration_seconds:.1f}s")
    print("=" * 60)

    formats = args.format.split(",")
    if "json" in formats:
        save_json_report(report, args.output)
    if "md" in formats:
        save_markdown_report(report, args.output)

    # Exit with error code if any tests failed
    sys.exit(0 if report.failed == 0 else 1)


if __name__ == "__main__":
    main()
