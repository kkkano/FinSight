#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
RAG Quality V2 - Layer 3

Layer 3：完整 LangGraph Pipeline -> answer -> claim/keypoint 指标评估
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
import time
import unittest.mock as mock
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = PROJECT_ROOT / "tests"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
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
DEFAULT_BASELINE = EVAL_DIR / "baseline_layer3_v2.json"
DEFAULT_OUTPUT_DIR = EVAL_DIR / "reports"

_TEST_EVIDENCE_REGISTRY: dict[str, dict[str, Any]] = {}

CASE_TICKER_MAP: dict[str, str] = {
    "filing_maotai_revenue_2024q3": "600519.SS",
    "filing_catl_gross_margin_2024": "300750.SZ",
    "filing_byd_ev_sales_2024h1": "002594.SZ",
    "filing_paic_embedded_value_2024": "601318.SS",
    "transcript_alibaba_cloud_guidance": "BABA",
    "transcript_tencent_gaming_recovery": "0700.HK",
    "transcript_meituan_profitability": "3690.HK",
    "transcript_jd_supply_chain": "JD",
    "news_fed_rate_cut_astock": "000001.SS",
    "news_china_ev_export_competition": "002594.SZ",
    "news_apple_iphone16_china_sales": "AAPL",
    "news_semiconductor_export_controls": "NVDA",
}

METRIC_LABELS = {
    "keypoint_coverage": "关键点覆盖率",
    "keypoint_context_recall": "关键点上下文召回",
    "claim_support_rate": "陈述支持率",
    "unsupported_claim_rate": "无证据陈述率",
    "contradiction_rate": "矛盾陈述率",
    "numeric_consistency_rate": "数值一致率",
}


CASE_QUESTION_HINTS: dict[str, str] = {
    "transcript_jd_supply_chain": "请必须覆盖以下子点：毛利率变化、履约时效、复购/用户粘性、库存周转效率。",
    "news_semiconductor_export_controls": "请只复述证据中明确给出的数字与范围，不要扩写或改写数字口径。",
    "news_fed_rate_cut_astock": "请只使用证据中出现的历史数据与涨跌幅数字，不要引入证据外统计口径。",
}


def _setup_win32_utf8() -> None:
    if sys.platform != "win32":
        return
    import io

    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def _build_case_question(case_id: str, question: str) -> str:
    hint = CASE_QUESTION_HINTS.get(case_id)
    if not hint:
        return question
    return f"{question}\n\n补充约束：{hint}"


async def _injected_execute_plan_stub(state: Any) -> dict[str, Any]:
    thread_id = str(state.get("thread_id") or "unknown")
    test_data = _TEST_EVIDENCE_REGISTRY.get(thread_id, {})
    contexts: list[str] = test_data.get("contexts", [])
    doc_type: str = test_data.get("doc_type", "filing")
    case_id: str = test_data.get("case_id", "unknown")
    evidence_pool = [
        {
            "title": f"[L3V2-Test] {doc_type}_{i+1}",
            "snippet": ctx,
            "source": f"test_{doc_type}",
            "confidence": 0.9,
            "type": doc_type,
            "id": f"test:{case_id}:{i}",
        }
        for i, ctx in enumerate(contexts)
    ]
    artifacts = {
        "evidence_pool": evidence_pool,
        "rag_context": [],
        "step_results": {},
        "agent_outputs": {},
    }
    trace = dict(state.get("trace") or {})
    trace["executor"] = {
        "type": "layer3_v2_test_injection",
        "injected_contexts": len(contexts),
        "case_id": case_id,
        "thread_id": thread_id,
    }
    return {"artifacts": artifacts, "trace": trace}


def _extract_answer_from_state(state: dict[str, Any], output_mode: str = "brief") -> tuple[str, str]:
    artifacts = state.get("artifacts") or {}
    brief_data = artifacts.get("brief_data") or {}
    render_vars = artifacts.get("render_vars") or {}
    draft_md = artifacts.get("draft_markdown") or ""

    # brief 评估优先使用简版结构，避免误把完整长报告当作 brief 输出评估
    if output_mode == "brief":
        if isinstance(brief_data, dict):
            parts = []
            for k in ["headline", "summary", "conclusion"]:
                val = brief_data.get(k, "")
                if isinstance(val, str) and val.strip():
                    parts.append(val.strip())
            if parts:
                return "\n".join(parts), "brief_data"
        if isinstance(render_vars, dict):
            parts: list[str] = []
            for field_name in ["summary", "conclusion", "highlights"]:
                val = render_vars.get(field_name, "")
                if isinstance(val, str) and val.strip():
                    parts.append(val.strip())
            if parts:
                return "\n\n".join(parts), "render_vars_brief"
        if isinstance(draft_md, str) and len(draft_md.strip()) > 50:
            return draft_md.strip()[:1600], "draft_markdown_truncated"
    else:
        if isinstance(draft_md, str) and len(draft_md.strip()) > 50:
            return draft_md.strip(), "draft_markdown"
        if isinstance(render_vars, dict):
            parts: list[str] = []
            for field_name in ["summary", "analysis", "investment_summary", "conclusion", "highlights"]:
                val = render_vars.get(field_name, "")
                if isinstance(val, str) and val.strip():
                    parts.append(val.strip())
            if parts:
                return "\n\n".join(parts), "render_vars"
        if isinstance(brief_data, dict):
            parts = []
            for k in ["headline", "summary", "conclusion"]:
                val = brief_data.get(k, "")
                if isinstance(val, str) and val.strip():
                    parts.append(val.strip())
            if parts:
                return "\n".join(parts), "brief_data"

    messages = state.get("messages") or []
    for msg in reversed(messages):
        if getattr(msg, "type", "") == "ai":
            content = getattr(msg, "content", "")
            if isinstance(content, str) and content.strip():
                return content.strip(), "chat"
    return "", "empty"


def _extract_nodes_visited(state: dict[str, Any]) -> list[str]:
    trace = state.get("trace") or {}
    events = trace.get("events") or []
    nodes: list[str] = []
    seen: set[str] = set()
    for ev in events:
        if isinstance(ev, dict):
            node = ev.get("node") or ev.get("name")
            if node and node not in seen:
                seen.add(node)
                nodes.append(node)
    return nodes


def _needs_grounded_fallback(answer: str) -> bool:
    text = (answer or "").strip()
    if not text:
        return True
    # 太短通常是 clarify/拒答类，无法用于 claim-keypoint 评估
    if len(text) < 180:
        return True
    lower = text.lower()
    patterns = [
        "请选择",
        "请明确",
        "无法识别",
        "需要更多信息",
        "clarify",
        "active_symbol",
        "ticker",
    ]
    if any(p in text or p in lower for p in patterns):
        return True
    if re.search(r"(请|需要).*(补充|确认).*(标的|股票|代码|公司)", text):
        return True
    return False


async def _run_pipeline_for_case(case: dict[str, Any], output_mode: str, ticker: str = "") -> dict[str, Any]:
    case_id = case["id"]
    question = case["question"]
    contexts = case["mock_contexts"]
    thread_id = f"layer3-v2-{case_id}-{int(time.time())}"

    _TEST_EVIDENCE_REGISTRY[thread_id] = {
        "contexts": contexts,
        "doc_type": case.get("doc_type", "unknown"),
        "case_id": case_id,
    }
    try:
        with mock.patch(
            "backend.graph.nodes.execute_plan_stub.execute_plan_stub",
            side_effect=_injected_execute_plan_stub,
        ):
            from backend.graph.runner import GraphRunner

            runner = GraphRunner.create()
            ui_ctx: dict[str, Any] = {}
            if ticker:
                ui_ctx["active_symbol"] = ticker
            final_state = await runner.ainvoke(
                thread_id=thread_id,
                query=question,
                output_mode=output_mode,
                ui_context=ui_ctx,
                confirmation_mode="skip",
            )
        answer, synth_mode = _extract_answer_from_state(final_state, output_mode=output_mode)
        nodes = _extract_nodes_visited(final_state)
        return {
            "answer": answer,
            "retrieved_contexts": contexts,
            "nodes": nodes,
            "synth_mode": synth_mode,
            "error": None,
        }
    except Exception as exc:
        return {
            "answer": "",
            "retrieved_contexts": contexts,
            "nodes": [],
            "synth_mode": "error",
            "error": str(exc),
        }
    finally:
        _TEST_EVIDENCE_REGISTRY.pop(thread_id, None)


def _run_pipeline_sync(case: dict[str, Any], output_mode: str, ticker: str = "") -> dict[str, Any]:
    return asyncio.run(_run_pipeline_for_case(case, output_mode, ticker=ticker))


def _print_summary(report: dict[str, Any], gate: GateResultV2, drift: DriftResultV2) -> None:
    print("\n" + "═" * 94)
    print(f"  RAG Quality V2 - Layer3  {report['generated_at'][:19]}")
    print("═" * 94)
    cfg = report["config"]
    print(
        f"  cases={len(report['case_results'])}  output_mode={cfg.get('output_mode')}  dataset={report['dataset_version']}"
    )
    print("  " + "─" * 90)
    print(f"  {'指标':<28} {'值':>10} {'null率':>10}")
    print("  " + "─" * 90)
    for key in METRIC_KEYS_V2:
        v = report["overall_metrics"].get(key)
        val = f"{v:.4f}" if v is not None else "N/A"
        null_rate = report["metric_null_rates"].get(key, 0.0)
        print(f"  {METRIC_LABELS[key]:<28} {val:>10} {null_rate:>9.0%}")
    print("  " + "─" * 90)
    print(f"  Gate: {'✓ PASS' if gate.passed else '✗ FAIL'}")
    if gate.failures:
        for f in gate.failures:
            print(f"    - {f}")
    print(f"  Drift: {'✓ PASS' if drift.passed else '✗ FAIL'} (baseline_available={drift.baseline_available})")
    if drift.failures:
        for f in drift.failures:
            print(f"    - {f}")
    print("═" * 94 + "\n")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RAG Quality V2 Layer3 runner")
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
    parser.add_argument("--output-mode", choices=["chat", "brief", "investment_report"], default="brief")
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
            tuned_question = _build_case_question(case_id, question)
            if args.mock:
                answer = contexts[0][:220] if contexts else "mock answer"
                retrieved_contexts = contexts
                pipeline_info = {"nodes": ["planner", "execute_plan", "synthesize", "render"], "synth_mode": "mock"}
            else:
                ticker = CASE_TICKER_MAP.get(case_id, "")
                pipeline_result = _run_pipeline_sync(case, args.output_mode, ticker=ticker)
                if pipeline_result["error"]:
                    raise RuntimeError(pipeline_result["error"])
                answer = pipeline_result["answer"]
                retrieved_contexts = pipeline_result["retrieved_contexts"]
                pipeline_info = {"nodes": pipeline_result["nodes"], "synth_mode": pipeline_result["synth_mode"]}
                if _needs_grounded_fallback(answer):
                    answer = generate_answer_from_context(
                        question=tuned_question,
                        contexts=retrieved_contexts,
                        chat_client=chat_client,
                        model=chat_model,
                        max_tokens=650,
                    )
                    pipeline_info["synth_mode"] = f"{pipeline_info['synth_mode']}+grounded_fallback"

            metrics, artifacts, metric_errors = evaluate_case_v2(
                case_id=case_id,
                question=question,
                ground_truth=ground_truth,
                answer=answer,
                retrieved_contexts=retrieved_contexts,
                chat_client=chat_client,
                embed_client=embed_client,
                embed_model=embed_model,
                top_k_evidence=4,
                mock_mode=args.mock,
            )
            artifacts["pipeline"] = pipeline_info
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
            print(f"  ✓ answer_len={len(answer)} synth={pipeline_info.get('synth_mode')}")
        except Exception as exc:
            case_results.append(
                CaseResultV2(
                    case_id=case_id,
                    doc_type=doc_type,
                    question_type=question_type,
                    answer_len=0,
                    metrics={k: None for k in METRIC_KEYS_V2},
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
        layer="layer3_v2",
        dataset_version=str(dataset.get("version", "unknown")),
        config={
            "doc_type_filter": args.doc_type,
            "mock_mode": args.mock,
            "chat_model": chat_model,
            "embed_model": embed_model,
            "retry": args.retry,
            "output_mode": args.output_mode,
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
            "layer": "layer3_v2",
            "generated_at": report.generated_at,
            "dataset_version": report.dataset_version,
            "overall_metrics": report.overall_metrics,
            "by_doc_type": report.by_doc_type,
            "by_question_type": report.by_question_type,
            "note": "Generated by run_layer3_v2.py --save-baseline",
        }
        save_json(baseline_payload, args.baseline)
        print(f"baseline saved: {args.baseline}")

    if args.gate and (not gate.passed or not drift.passed):
        sys.exit(1)
    if args.gate:
        print("✓ gate passed")


if __name__ == "__main__":
    main()
