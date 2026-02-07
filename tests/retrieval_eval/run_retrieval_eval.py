#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Retrieval quality baseline runner (RAG v2).

Outputs:
- Recall@K
- nDCG@K
- citation coverage
- latency (mean / p95)

Usage:
  python tests/retrieval_eval/run_retrieval_eval.py
  python tests/retrieval_eval/run_retrieval_eval.py --gate
  python tests/retrieval_eval/run_retrieval_eval.py --output-dir tests/retrieval_eval/reports --report-prefix ci
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.rag.hybrid_service import HybridRAGService, RAGDocument


DEFAULT_DATASET = PROJECT_ROOT / "tests" / "retrieval_eval" / "dataset_v1.json"
DEFAULT_THRESHOLDS = PROJECT_ROOT / "tests" / "retrieval_eval" / "thresholds.json"
DEFAULT_BASELINE = PROJECT_ROOT / "tests" / "retrieval_eval" / "baseline_results.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "tests" / "retrieval_eval" / "reports"


@dataclass
class GateResult:
    passed: bool
    failed_metrics: list[str]
    thresholds: dict[str, float]


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _safe_mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(statistics.fmean(values))


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    idx = max(0, math.ceil(0.95 * len(sorted_values)) - 1)
    return float(sorted_values[idx])


def compute_recall_at_k(expected_ids: list[str], retrieved_ids: list[str]) -> float:
    expected = [x for x in expected_ids if x]
    if not expected:
        return 1.0
    retrieved = set(x for x in retrieved_ids if x)
    hit = len(set(expected) & retrieved)
    return hit / len(set(expected))


def _dcg_at_k(retrieved_ids: list[str], relevance_map: dict[str, float], k: int) -> float:
    score = 0.0
    for idx, doc_id in enumerate(retrieved_ids[: max(1, k)]):
        rel = float(relevance_map.get(doc_id, 0.0))
        if rel <= 0:
            continue
        score += rel / math.log2(idx + 2.0)
    return score


def compute_ndcg_at_k(retrieved_ids: list[str], relevance_map: dict[str, float], k: int) -> float:
    k = max(1, int(k))
    dcg = _dcg_at_k(retrieved_ids, relevance_map, k)
    ideal_rels = sorted((float(v) for v in relevance_map.values() if float(v) > 0), reverse=True)[:k]
    if not ideal_rels:
        return 1.0
    idcg = 0.0
    for idx, rel in enumerate(ideal_rels):
        idcg += rel / math.log2(idx + 2.0)
    if idcg <= 0:
        return 1.0
    return dcg / idcg


def _select_predicted_citations(hits: list[dict[str, Any]], citation_top_k: int) -> list[str]:
    if citation_top_k <= 0:
        return []
    selected: list[str] = []
    for hit in hits:
        source_id = str(hit.get("source_id") or "").strip()
        if not source_id:
            continue
        # citation candidates should at least have a URL or title
        title = str(hit.get("title") or "").strip()
        url = str(hit.get("url") or "").strip()
        if not title and not url:
            continue
        selected.append(source_id)
        if len(selected) >= citation_top_k:
            break
    return selected


def compute_citation_coverage(gold_citation_ids: list[str], predicted_citation_ids: list[str]) -> float:
    gold = [x for x in gold_citation_ids if x]
    if not gold:
        return 1.0
    predicted = set(x for x in predicted_citation_ids if x)
    hit = len(set(gold) & predicted)
    return hit / len(set(gold))


def _build_service(backend: str, postgres_dsn: str | None = None) -> HybridRAGService:
    backend_norm = (backend or "memory").strip().lower()
    if backend_norm == "memory":
        return HybridRAGService.for_testing(backend="memory")

    if backend_norm == "postgres":
        dsn = (postgres_dsn or os.getenv("RAG_V2_POSTGRES_DSN") or os.getenv("LANGGRAPH_CHECKPOINT_POSTGRES_DSN") or "").strip()
        if not dsn:
            raise ValueError("postgres backend requested but no DSN provided")
        return HybridRAGService(
            backend="postgres",
            vector_dim=96,
            rrf_k=60,
            postgres_dsn=dsn,
            allow_memory_fallback=False,
        )

    # auto path (mostly for local experiments), may fallback to memory
    return HybridRAGService.from_env()


def _evaluate_case(
    service: HybridRAGService,
    case: dict[str, Any],
    *,
    top_k: int,
    citation_top_k: int,
) -> dict[str, Any]:
    case_id = str(case.get("id") or "").strip()
    bucket = str(case.get("bucket") or "unknown").strip() or "unknown"
    query = str(case.get("query") or "").strip()
    corpus = case.get("corpus") if isinstance(case.get("corpus"), list) else []
    relevance_map = case.get("relevance") if isinstance(case.get("relevance"), dict) else {}
    gold_evidence_ids = [str(x).strip() for x in case.get("gold_evidence_ids", []) if str(x).strip()]
    gold_citation_ids = [str(x).strip() for x in case.get("gold_citation_ids", []) if str(x).strip()]
    if not gold_citation_ids:
        gold_citation_ids = list(gold_evidence_ids)

    collection = f"retrieval_eval:{case_id}"
    docs: list[RAGDocument] = []
    for item in corpus:
        if not isinstance(item, dict):
            continue
        source_id = str(item.get("id") or "").strip()
        content = str(item.get("content") or "").strip()
        if not source_id or not content:
            continue
        docs.append(
            RAGDocument(
                collection=collection,
                scope="ephemeral",
                source_id=source_id,
                content=content,
                title=str(item.get("title") or "").strip() or None,
                url=str(item.get("url") or "").strip() or None,
                source=str(item.get("source") or bucket).strip() or bucket,
                metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
                expires_at=None,
            )
        )

    ingest_t0 = time.perf_counter()
    ingest_stats = service.ingest_documents(docs)
    ingest_ms = (time.perf_counter() - ingest_t0) * 1000.0

    search_t0 = time.perf_counter()
    hits = service.hybrid_search(query, collection=collection, top_k=top_k)
    search_ms = (time.perf_counter() - search_t0) * 1000.0

    retrieved_ids = [str(hit.get("source_id") or "").strip() for hit in hits if str(hit.get("source_id") or "").strip()]
    predicted_citation_ids = _select_predicted_citations(hits, citation_top_k=citation_top_k)

    recall = compute_recall_at_k(gold_evidence_ids, retrieved_ids)
    ndcg = compute_ndcg_at_k(retrieved_ids, {str(k): float(v) for k, v in relevance_map.items()}, top_k)
    citation_coverage = compute_citation_coverage(gold_citation_ids, predicted_citation_ids)

    return {
        "id": case_id,
        "bucket": bucket,
        "query": query,
        "gold_evidence_ids": gold_evidence_ids,
        "gold_citation_ids": gold_citation_ids,
        "retrieved_ids": retrieved_ids,
        "predicted_citation_ids": predicted_citation_ids,
        "recall_at_k": recall,
        "ndcg_at_k": ndcg,
        "citation_coverage": citation_coverage,
        "latency_ms": search_ms,
        "ingest_ms": ingest_ms,
        "indexed": int(ingest_stats.get("indexed", 0)),
        "skipped": int(ingest_stats.get("skipped", 0)),
    }


def _aggregate(results: list[dict[str, Any]]) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    recalls = [float(r["recall_at_k"]) for r in results]
    ndcgs = [float(r["ndcg_at_k"]) for r in results]
    citation_coverages = [float(r["citation_coverage"]) for r in results]
    latencies = [float(r["latency_ms"]) for r in results]

    overall = {
        "recall_at_k": _safe_mean(recalls),
        "ndcg_at_k": _safe_mean(ndcgs),
        "citation_coverage": _safe_mean(citation_coverages),
        "latency_mean_ms": _safe_mean(latencies),
        "latency_p95_ms": _p95(latencies),
    }

    bucket_groups: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        bucket_groups.setdefault(str(r["bucket"]), []).append(r)

    bucket_metrics: dict[str, dict[str, float]] = {}
    for bucket, items in bucket_groups.items():
        bucket_metrics[bucket] = {
            "count": float(len(items)),
            "recall_at_k": _safe_mean([float(x["recall_at_k"]) for x in items]),
            "ndcg_at_k": _safe_mean([float(x["ndcg_at_k"]) for x in items]),
            "citation_coverage": _safe_mean([float(x["citation_coverage"]) for x in items]),
            "latency_mean_ms": _safe_mean([float(x["latency_ms"]) for x in items]),
            "latency_p95_ms": _p95([float(x["latency_ms"]) for x in items]),
        }
    return overall, bucket_metrics


def _load_baseline(path: Path) -> dict[str, float] | None:
    if not path.exists():
        return None
    data = _load_json(path)
    overall = data.get("overall_metrics")
    if not isinstance(overall, dict):
        return None
    return {k: float(v) for k, v in overall.items() if isinstance(v, (int, float))}


def _gate(overall: dict[str, float], thresholds: dict[str, float]) -> GateResult:
    failed: list[str] = []
    recall_min = float(thresholds.get("recall_at_k_min", 0.0))
    ndcg_min = float(thresholds.get("ndcg_at_k_min", 0.0))
    cite_min = float(thresholds.get("citation_coverage_min", 0.0))
    latency_max = float(thresholds.get("latency_p95_ms_max", 10_000.0))

    if float(overall.get("recall_at_k", 0.0)) < recall_min:
        failed.append("recall_at_k")
    if float(overall.get("ndcg_at_k", 0.0)) < ndcg_min:
        failed.append("ndcg_at_k")
    if float(overall.get("citation_coverage", 0.0)) < cite_min:
        failed.append("citation_coverage")
    if float(overall.get("latency_p95_ms", 10_000.0)) > latency_max:
        failed.append("latency_p95_ms")

    return GateResult(passed=(len(failed) == 0), failed_metrics=failed, thresholds=thresholds)


def _format_pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _to_markdown(
    payload: dict[str, Any],
    *,
    gate: GateResult,
    baseline_overall: dict[str, float] | None,
) -> str:
    overall = payload["overall_metrics"]
    bucket_metrics = payload["bucket_metrics"]
    compare = payload["comparison"]

    lines: list[str] = []
    lines.append("# Retrieval Eval Report")
    lines.append("")
    lines.append(f"- Run ID: `{payload['run_id']}`")
    lines.append(f"- Dataset: `{payload['dataset_path']}`")
    lines.append(f"- Backend: `{payload['backend']}`")
    lines.append(f"- Cases: `{payload['case_count']}`")
    lines.append(f"- Top-K: `{payload['top_k']}` | Citation Top-K: `{payload['citation_top_k']}`")
    lines.append("")
    lines.append("## Overall")
    lines.append("")
    lines.append("| Metric | Current | Baseline | Delta | Gate | Status |")
    lines.append("|---|---:|---:|---:|---:|---|")

    def _status(metric: str, ok: bool) -> str:
        return "PASS" if ok else f"FAIL ({metric})"

    recall_cur = float(overall["recall_at_k"])
    ndcg_cur = float(overall["ndcg_at_k"])
    cite_cur = float(overall["citation_coverage"])
    lat_cur = float(overall["latency_p95_ms"])

    recall_ok = recall_cur >= float(gate.thresholds["recall_at_k_min"])
    ndcg_ok = ndcg_cur >= float(gate.thresholds["ndcg_at_k_min"])
    cite_ok = cite_cur >= float(gate.thresholds["citation_coverage_min"])
    lat_ok = lat_cur <= float(gate.thresholds["latency_p95_ms_max"])

    lines.append(
        f"| Recall@K | {_format_pct(recall_cur)} | {_format_pct(float((baseline_overall or {}).get('recall_at_k', 0.0)))} | "
        f"{_format_pct(float(compare['delta'].get('recall_at_k', 0.0)))} | >= {_format_pct(float(gate.thresholds['recall_at_k_min']))} | {_status('recall_at_k', recall_ok)} |"
    )
    lines.append(
        f"| nDCG@K | {_format_pct(ndcg_cur)} | {_format_pct(float((baseline_overall or {}).get('ndcg_at_k', 0.0)))} | "
        f"{_format_pct(float(compare['delta'].get('ndcg_at_k', 0.0)))} | >= {_format_pct(float(gate.thresholds['ndcg_at_k_min']))} | {_status('ndcg_at_k', ndcg_ok)} |"
    )
    lines.append(
        f"| Citation Coverage | {_format_pct(cite_cur)} | {_format_pct(float((baseline_overall or {}).get('citation_coverage', 0.0)))} | "
        f"{_format_pct(float(compare['delta'].get('citation_coverage', 0.0)))} | >= {_format_pct(float(gate.thresholds['citation_coverage_min']))} | {_status('citation_coverage', cite_ok)} |"
    )
    lines.append(
        f"| Latency P95 (ms) | {lat_cur:.2f} | {float((baseline_overall or {}).get('latency_p95_ms', 0.0)):.2f} | "
        f"{float(compare['delta'].get('latency_p95_ms', 0.0)):+.2f} | <= {float(gate.thresholds['latency_p95_ms_max']):.2f} | {_status('latency_p95_ms', lat_ok)} |"
    )
    lines.append("")
    lines.append("## By Bucket")
    lines.append("")
    lines.append("| Bucket | Count | Recall@K | nDCG@K | Citation Coverage | Latency P95 (ms) |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for bucket in sorted(bucket_metrics.keys()):
        item = bucket_metrics[bucket]
        lines.append(
            f"| {bucket} | {int(item['count'])} | {_format_pct(float(item['recall_at_k']))} | {_format_pct(float(item['ndcg_at_k']))} | "
            f"{_format_pct(float(item['citation_coverage']))} | {float(item['latency_p95_ms']):.2f} |"
        )

    if not gate.passed:
        lines.append("")
        lines.append("## Gate Failures")
        lines.append("")
        for metric in gate.failed_metrics:
            lines.append(f"- {metric}")

    return "\n".join(lines) + "\n"


def run_eval(
    *,
    dataset_path: Path,
    thresholds_path: Path,
    baseline_path: Path,
    backend: str,
    postgres_dsn: str | None,
    top_k: int | None,
    citation_top_k: int | None,
) -> dict[str, Any]:
    dataset = _load_json(dataset_path)
    threshold_config = _load_json(thresholds_path)
    baseline_overall = _load_baseline(baseline_path)

    threshold_top_k = int(threshold_config.get("top_k", 6))
    threshold_citation_top_k = int(threshold_config.get("citation_top_k", 3))
    effective_top_k = int(top_k) if top_k is not None else threshold_top_k
    effective_citation_top_k = int(citation_top_k) if citation_top_k is not None else threshold_citation_top_k
    cases = dataset.get("cases") if isinstance(dataset.get("cases"), list) else []

    service = _build_service(backend=backend, postgres_dsn=postgres_dsn)

    t0 = time.perf_counter()
    case_results: list[dict[str, Any]] = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        result = _evaluate_case(
            service,
            case,
            top_k=effective_top_k,
            citation_top_k=effective_citation_top_k,
        )
        case_results.append(result)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    overall, bucket_metrics = _aggregate(case_results)
    comparison_delta = {}
    if baseline_overall:
        for key, value in overall.items():
            comparison_delta[key] = float(value) - float(baseline_overall.get(key, 0.0))
    else:
        for key in overall.keys():
            comparison_delta[key] = 0.0

    payload = {
        "run_id": datetime.now(timezone.utc).strftime("retrieval-%Y%m%d-%H%M%S"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset_version": str(dataset.get("version") or "unknown"),
        "dataset_path": str(dataset_path),
        "thresholds_path": str(thresholds_path),
        "baseline_path": str(baseline_path),
        "backend": service.backend_name,
        "backend_requested": backend,
        "top_k": effective_top_k,
        "citation_top_k": effective_citation_top_k,
        "case_count": len(case_results),
        "elapsed_ms": elapsed_ms,
        "overall_metrics": overall,
        "bucket_metrics": bucket_metrics,
        "case_results": case_results,
        "comparison": {
            "baseline_available": baseline_overall is not None,
            "baseline_overall": baseline_overall or {},
            "delta": comparison_delta,
        },
    }
    return payload


def save_reports(
    payload: dict[str, Any],
    *,
    output_dir: Path,
    report_prefix: str,
    gate: GateResult,
    baseline_overall: dict[str, float] | None,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = payload["run_id"]
    prefix = f"{report_prefix}_" if report_prefix else ""
    json_path = output_dir / f"{prefix}{run_id}.json"
    md_path = output_dir / f"{prefix}{run_id}.md"

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(
            {
                **payload,
                "gate": {
                    "passed": gate.passed,
                    "failed_metrics": gate.failed_metrics,
                    "thresholds": gate.thresholds,
                },
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    markdown = _to_markdown(payload, gate=gate, baseline_overall=baseline_overall)
    with md_path.open("w", encoding="utf-8") as f:
        f.write(markdown)

    return json_path, md_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run retrieval quality baseline evaluation")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET), help="Path to evaluation dataset json")
    parser.add_argument("--thresholds", default=str(DEFAULT_THRESHOLDS), help="Path to thresholds json")
    parser.add_argument("--baseline", default=str(DEFAULT_BASELINE), help="Path to baseline results json")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory to store reports")
    parser.add_argument("--report-prefix", default="", help="Optional report filename prefix")
    parser.add_argument("--backend", default="memory", choices=["memory", "postgres", "auto"], help="RAG backend")
    parser.add_argument("--postgres-dsn", default="", help="Postgres DSN (required for --backend postgres)")
    parser.add_argument("--top-k", type=int, default=None, help="Override top-k")
    parser.add_argument("--citation-top-k", type=int, default=None, help="Override citation top-k")
    parser.add_argument("--gate", action="store_true", help="Fail (exit 1) when threshold gate fails")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dataset_path = Path(args.dataset).resolve()
    thresholds_path = Path(args.thresholds).resolve()
    baseline_path = Path(args.baseline).resolve()
    output_dir = Path(args.output_dir).resolve()

    payload = run_eval(
        dataset_path=dataset_path,
        thresholds_path=thresholds_path,
        baseline_path=baseline_path,
        backend=args.backend,
        postgres_dsn=(args.postgres_dsn or "").strip() or None,
        top_k=args.top_k,
        citation_top_k=args.citation_top_k,
    )

    threshold_config = _load_json(thresholds_path)
    thresholds = threshold_config.get("gates") if isinstance(threshold_config.get("gates"), dict) else {}
    threshold_values = {k: float(v) for k, v in thresholds.items() if isinstance(v, (int, float))}
    gate = _gate(payload["overall_metrics"], threshold_values)

    baseline_overall = payload["comparison"]["baseline_overall"] if payload["comparison"]["baseline_available"] else None
    json_path, md_path = save_reports(
        payload,
        output_dir=output_dir,
        report_prefix=args.report_prefix,
        gate=gate,
        baseline_overall=baseline_overall,
    )

    print("=" * 72)
    print("Retrieval Eval Baseline")
    print("=" * 72)
    print(f"Run ID: {payload['run_id']}")
    print(f"Backend: {payload['backend']} (requested={payload['backend_requested']})")
    print(f"Cases: {payload['case_count']}")
    print(f"Recall@K: {payload['overall_metrics']['recall_at_k']:.4f}")
    print(f"nDCG@K: {payload['overall_metrics']['ndcg_at_k']:.4f}")
    print(f"Citation Coverage: {payload['overall_metrics']['citation_coverage']:.4f}")
    print(f"Latency P95 (ms): {payload['overall_metrics']['latency_p95_ms']:.2f}")
    print(f"Gate: {'PASS' if gate.passed else 'FAIL'}")
    if gate.failed_metrics:
        print(f"Failed metrics: {', '.join(gate.failed_metrics)}")
    print(f"JSON report: {json_path}")
    print(f"Markdown report: {md_path}")
    print("=" * 72)

    if args.gate and not gate.passed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

