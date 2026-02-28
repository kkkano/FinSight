#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
RAG Quality V2 - Layer 1

Layer 1：mock_contexts -> answer -> claim/keypoint 指标评估
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = PROJECT_ROOT / "tests"
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from rag_qualityV2.clients_v2 import create_chat_client_from_env, create_embedding_client_from_env
from rag_qualityV2.engine_v2 import (
    build_eval_report_v2,
    check_drift_v2,
    check_gates_v2,
    evaluate_case_v2,
    generate_answer_from_context,
    load_json,
    save_json,
)
from rag_qualityV2.types_v2 import CaseResultV2, DriftResultV2, GateResultV2, METRIC_KEYS_V2

EVAL_DIR = Path(__file__).parent
DEFAULT_DATASET = PROJECT_ROOT / "tests" / "rag_quality" / "dataset.json"
DEFAULT_THRESHOLDS = EVAL_DIR / "thresholds_v2.json"
DEFAULT_BASELINE = EVAL_DIR / "baseline_layer1_v2.json"
DEFAULT_OUTPUT_DIR = EVAL_DIR / "reports"

METRIC_LABELS = {
    "keypoint_coverage": "关键点覆盖率",
    "keypoint_context_recall": "关键点上下文召回",
    "claim_support_rate": "陈述支持率",
    "unsupported_claim_rate": "无证据陈述率",
    "contradiction_rate": "矛盾陈述率",
    "numeric_consistency_rate": "数值一致率",
}


def _setup_win32_utf8() -> None:
    if sys.platform != "win32":
        return
    import io

    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def _print_summary(report: dict[str, Any], gate: GateResultV2, drift: DriftResultV2) -> None:
    print("\n" + "═" * 88)
    print(f"  RAG Quality V2 - Layer1  {report['generated_at'][:19]}")
    print("═" * 88)
    print(f"  cases={len(report['case_results'])}  dataset={report['dataset_version']}")
    print("  " + "─" * 84)
    print(f"  {'指标':<28} {'值':>10} {'null率':>10}")
    print("  " + "─" * 84)
    for key in METRIC_KEYS_V2:
        v = report["overall_metrics"].get(key)
        val = f"{v:.4f}" if v is not None else "N/A"
        null_rate = report["metric_null_rates"].get(key, 0.0)
        print(f"  {METRIC_LABELS[key]:<28} {val:>10} {null_rate:>9.0%}")
    print("  " + "─" * 84)
    print(f"  Gate: {'✓ PASS' if gate.passed else '✗ FAIL'}")
    if gate.failures:
        for f in gate.failures:
            print(f"    - {f}")
    print(f"  Drift: {'✓ PASS' if drift.passed else '✗ FAIL'} (baseline_available={drift.baseline_available})")
    if drift.failures:
        for f in drift.failures:
            print(f"    - {f}")
    print("═" * 88 + "\n")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RAG Quality V2 Layer1 runner")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--thresholds", type=Path, default=DEFAULT_THRESHOLDS)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--doc-type", choices=["filing", "transcript", "news"], default=None)
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--gate", action="store_true")
    parser.add_argument("--save-baseline", action="store_true")
    parser.add_argument("--delay", type=int, default=5)
    parser.add_argument("--intra-case-delay", type=int, default=5)
    parser.add_argument("--retry", type=int, default=2)
    return parser.parse_args()


def main() -> None:
    _setup_win32_utf8()
    try:
        from dotenv import load_dotenv

        load_dotenv(PROJECT_ROOT / ".env", override=False)
    except Exception:
        pass

    args = _parse_args()
    dataset = load_json(args.dataset)
    thresholds = load_json(args.thresholds)
    cases = dataset.get("cases", [])
    if args.doc_type:
        cases = [c for c in cases if c.get("doc_type") == args.doc_type]

    if not args.mock:
        chat_client = create_chat_client_from_env()
        embed_client = create_embedding_client_from_env()
        chat_model = chat_client.default_model
        embed_model = embed_client.default_model
    else:
        chat_client = None
        embed_client = None
        chat_model = "mock"
        embed_model = "mock"

    case_results: list[CaseResultV2] = []
    for idx, case in enumerate(cases, 1):
        if not args.mock and idx > 1 and args.delay > 0:
            time.sleep(args.delay)

        case_id = str(case["id"])
        question = str(case["question"])
        ground_truth = str(case["ground_truth"])
        contexts = [str(x) for x in case.get("mock_contexts", [])]
        doc_type = str(case.get("doc_type", "unknown"))
        question_type = str(case.get("question_type", "factoid"))

        print(f"[{idx:02d}/{len(cases):02d}] {case_id}")
        try:
            if args.mock:
                answer = contexts[0][:220] if contexts else "mock answer"
            else:
                answer = generate_answer_from_context(
                    question=question,
                    contexts=contexts,
                    chat_client=chat_client,
                    model=chat_model,
                    max_tokens=700,
                )

            metrics, artifacts, metric_errors = evaluate_case_v2(
                case_id=case_id,
                question=question,
                ground_truth=ground_truth,
                answer=answer,
                retrieved_contexts=contexts,
                chat_client=chat_client,
                embed_client=embed_client,
                embed_model=embed_model,
                top_k_evidence=4,
                mock_mode=args.mock,
            )
            case_results.append(
                CaseResultV2(
                    case_id=case_id,
                    doc_type=doc_type,
                    question_type=question_type,
                    answer_len=len(answer),
                    metrics=metrics,
                    metric_errors=metric_errors,
                    judge_artifacts=artifacts,
                )
            )
            print(f"  ✓ answer_len={len(answer)}")
        except Exception as exc:
            case_results.append(
                CaseResultV2(
                    case_id=case_id,
                    doc_type=doc_type,
                    question_type=question_type,
                    answer_len=0,
                    metrics={k: None for k in METRIC_KEYS_V2},
                    metric_errors={},
                    error=str(exc),
                )
            )
            print(f"  ✗ {exc}")

        if (not args.mock) and args.intra_case_delay > 0 and idx < len(cases):
            time.sleep(args.intra_case_delay)

    empty_gate = GateResultV2(passed=True, failures=[])
    empty_drift = DriftResultV2(
        enabled=True,
        baseline_available=False,
        passed=True,
        deltas={},
        failures=[],
        baseline_run_id=None,
    )
    report = build_eval_report_v2(
        layer="layer1_v2",
        dataset_version=str(dataset.get("version", "unknown")),
        config={
            "doc_type_filter": args.doc_type,
            "mock_mode": args.mock,
            "chat_model": chat_model,
            "embed_model": embed_model,
            "retry": args.retry,
        },
        case_results=case_results,
        gate_result=empty_gate,
        drift_result=empty_drift,
    )

    gate = check_gates_v2(report, thresholds)
    if args.mock:
        drift = DriftResultV2(
            enabled=False,
            baseline_available=False,
            passed=True,
            deltas={},
            failures=[],
            baseline_run_id=None,
        )
    else:
        baseline_data = load_json(args.baseline) if args.baseline.exists() else None
        drift = check_drift_v2(report.overall_metrics, baseline_data, thresholds)

    report.gate_result = gate.to_dict()
    report.drift_result = drift.to_dict()
    _print_summary(report.to_dict(), gate, drift)

    run_id = report.run_id
    output_path = args.output or (args.output_dir / f"{run_id}.json")
    save_json(report.to_dict(), output_path)
    print(f"report saved: {output_path}")

    if args.save_baseline:
        baseline_payload = {
            "run_id": report.run_id,
            "layer": "layer1_v2",
            "generated_at": report.generated_at,
            "dataset_version": report.dataset_version,
            "overall_metrics": report.overall_metrics,
            "by_doc_type": report.by_doc_type,
            "by_question_type": report.by_question_type,
            "note": "Generated by run_layer1_v2.py --save-baseline",
        }
        save_json(baseline_payload, args.baseline)
        print(f"baseline saved: {args.baseline}")

    if args.gate and (not gate.passed or not drift.passed):
        sys.exit(1)
    if args.gate:
        print("✓ gate passed")


if __name__ == "__main__":
    main()
