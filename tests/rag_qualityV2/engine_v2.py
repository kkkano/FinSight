from __future__ import annotations

import json
import math
import random
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from rag_qualityV2.prompts_v2 import (
    ANSWER_SYSTEM_PROMPT,
    CLAIM_JUDGE_SYSTEM_PROMPT,
    CLAIM_SYSTEM_PROMPT,
    KEYPOINT_JUDGE_SYSTEM_PROMPT,
    KEYPOINT_SYSTEM_PROMPT,
    build_answer_user_prompt,
    build_claim_judge_user_prompt,
    build_claim_user_prompt,
    build_keypoint_judge_user_prompt,
    build_keypoint_user_prompt,
)
from rag_qualityV2.types_v2 import (
    CaseResultV2,
    DriftResultV2,
    EvalReportV2,
    GateResultV2,
    METRIC_KEYS_V2,
)


class ChatClientLike(Protocol):
    default_model: str

    def complete_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        max_tokens: int = 1200,
        temperature: float = 0.0,
    ) -> str: ...

    def complete_json(
        self,
        *,
        schema_name: str,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        max_tokens: int = 1200,
        temperature: float = 0.0,
    ) -> dict[str, Any]: ...


class EmbeddingClientLike(Protocol):
    default_model: str

    def embed_texts(self, texts: list[str], *, model: str | None = None, batch_size: int = 32) -> list[list[float]]: ...


def _safe_mean(values: list[float | None]) -> float | None:
    clean = [float(v) for v in values if v is not None]
    if not clean:
        return None
    return round(sum(clean) / len(clean), 4)


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def chunk_text(text: str, chunk_size: int = 300, overlap: int = 50) -> list[str]:
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            boundary = max(
                text.rfind("。", start + chunk_size // 2, end),
                text.rfind("！", start + chunk_size // 2, end),
                text.rfind("？", start + chunk_size // 2, end),
                text.rfind("\n", start + chunk_size // 2, end),
            )
            if boundary > start:
                end = boundary + 1
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        start = max(start + 1, end - overlap)
    return chunks


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def retrieve_top_k_chunks(
    *,
    query: str,
    contexts: list[str],
    embed_client: EmbeddingClientLike,
    embed_model: str,
    top_k: int = 5,
    chunk_size: int = 300,
    chunk_overlap: int = 50,
) -> tuple[list[str], int]:
    chunks: list[str] = []
    for ctx in contexts:
        chunks.extend(chunk_text(ctx, chunk_size=chunk_size, overlap=chunk_overlap))
    if not chunks:
        return [], 0
    vectors = embed_client.embed_texts([query, *chunks], model=embed_model)
    q_vec = vectors[0]
    scored = [(idx, cosine_similarity(q_vec, vec)) for idx, vec in enumerate(vectors[1:])]
    scored.sort(key=lambda x: x[1], reverse=True)
    picked: list[str] = []
    seen: set[str] = set()
    for idx, _score in scored:
        t = chunks[idx]
        if t in seen:
            continue
        seen.add(t)
        picked.append(t)
        if len(picked) >= top_k:
            break
    return picked, len(chunks)


def generate_answer_from_context(
    *,
    question: str,
    contexts: list[str],
    chat_client: ChatClientLike,
    model: str | None = None,
    max_tokens: int = 1200,
) -> str:
    return chat_client.complete_text(
        system_prompt=ANSWER_SYSTEM_PROMPT,
        user_prompt=build_answer_user_prompt(question, contexts),
        model=model,
        temperature=0.0,
        max_tokens=max_tokens,
    ).strip()


def _split_sentences(text: str, max_items: int) -> list[str]:
    parts = re.split(r"[。！？\n]", text or "")
    cleaned = [p.strip(" \t\r\n-•") for p in parts if len(p.strip()) >= 4]
    return cleaned[:max_items]


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").lower())


def _extract_numbers(text: str) -> list[str]:
    return re.findall(r"-?\d+(?:\.\d+)?%?", text or "")


def _looks_like_time_marker_number(num: str) -> bool:
    # 仅年份/日期类数字不算“数值一致率”里的财务数值 claim
    n = (num or "").strip().rstrip("%")
    if not n:
        return False
    if n.isdigit() and len(n) == 4 and n.startswith(("19", "20")):
        return True
    return False


def _is_numeric_claim_by_rule(claim: str) -> bool:
    nums = _extract_numbers(claim)
    if not nums:
        return False
    effective = [x for x in nums if not _looks_like_time_marker_number(x)]
    return bool(effective)


def extract_keypoints(
    *,
    question: str,
    ground_truth: str,
    chat_client: ChatClientLike,
    model: str | None = None,
) -> list[str]:
    try:
        data = chat_client.complete_json(
            schema_name="extract_keypoints",
            system_prompt=KEYPOINT_SYSTEM_PROMPT,
            user_prompt=build_keypoint_user_prompt(question, ground_truth),
            model=model,
            max_tokens=1400,
            temperature=0.0,
        )
        raw = data.get("keypoints") or []
        out = [str(x).strip() for x in raw if str(x).strip()]
        return out[:8] if out else _split_sentences(ground_truth, 8)
    except Exception:
        return _split_sentences(ground_truth, 8)


def extract_claims(
    *,
    answer: str,
    chat_client: ChatClientLike,
    model: str | None = None,
) -> list[str]:
    try:
        data = chat_client.complete_json(
            schema_name="extract_claims",
            system_prompt=CLAIM_SYSTEM_PROMPT,
            user_prompt=build_claim_user_prompt(answer),
            model=model,
            max_tokens=1400,
            temperature=0.0,
        )
        raw = data.get("claims") or []
        out = [str(x).strip() for x in raw if str(x).strip()]
        return out[:12] if out else _split_sentences(answer, 12)
    except Exception:
        return _split_sentences(answer, 12)


def _top_evidence_for_text(
    *,
    text: str,
    contexts: list[str],
    context_vectors: list[list[float]],
    embed_client: EmbeddingClientLike,
    embed_model: str,
    top_k_evidence: int,
) -> list[str]:
    if not contexts:
        return []
    q_vec = embed_client.embed_texts([text], model=embed_model)[0]
    scored = [(i, cosine_similarity(q_vec, v)) for i, v in enumerate(context_vectors)]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [contexts[i] for i, _ in scored[:top_k_evidence]]


def _build_evidence_map_batch(
    *,
    queries: list[str],
    contexts: list[str],
    embed_client: EmbeddingClientLike,
    embed_model: str,
    top_k_evidence: int,
) -> dict[str, list[str]]:
    if not queries or not contexts:
        return {}
    payload = [*contexts, *queries]
    vectors = embed_client.embed_texts(payload, model=embed_model)
    n_ctx = len(contexts)
    context_vectors = vectors[:n_ctx]
    query_vectors = vectors[n_ctx:]
    evidence_map: dict[str, list[str]] = {}
    for query, q_vec in zip(queries, query_vectors):
        scored = [(i, cosine_similarity(q_vec, v)) for i, v in enumerate(context_vectors)]
        scored.sort(key=lambda x: x[1], reverse=True)
        evidence_map[query] = [contexts[i] for i, _ in scored[:top_k_evidence]]
    return evidence_map


def _fallback_claim_label(claim: str, evidences: list[str]) -> str:
    normalized_claim = _normalize_text(claim)
    for ev in evidences:
        if normalized_claim and normalized_claim in _normalize_text(ev):
            return "supported"
    claim_nums = _extract_numbers(claim)
    if claim_nums:
        all_ev_nums = []
        for ev in evidences:
            all_ev_nums.extend(_extract_numbers(ev))
        if all_ev_nums and all(n not in all_ev_nums for n in claim_nums):
            return "unsupported"
    return "unsupported"


def judge_claim(
    *,
    claim: str,
    evidences: list[str],
    chat_client: ChatClientLike,
    model: str | None = None,
) -> dict[str, Any]:
    try:
        data = chat_client.complete_json(
            schema_name="judge_claim",
            system_prompt=CLAIM_JUDGE_SYSTEM_PROMPT,
            user_prompt=build_claim_judge_user_prompt(claim, evidences),
            model=model,
            max_tokens=900,
            temperature=0.0,
        )
        label = str(data.get("label", "")).strip().lower()
        if label not in {"supported", "unsupported", "contradicted"}:
            label = _fallback_claim_label(claim, evidences)
        claim_nums = _extract_numbers(claim)
        evidence_nums: list[str] = []
        for ev in evidences:
            evidence_nums.extend(_extract_numbers(ev))
        is_numeric = _is_numeric_claim_by_rule(claim) or bool(data.get("is_numeric_claim", False))
        numeric_consistent = bool(data.get("numeric_consistent", False))
        # 后处理兜底：如果 claim 中所有有效数字都在证据中出现，则视为一致
        effective_nums = [x for x in claim_nums if not _looks_like_time_marker_number(x)]
        if is_numeric and effective_nums:
            if all(x in evidence_nums for x in effective_nums):
                numeric_consistent = True
            elif all(x not in evidence_nums for x in effective_nums):
                numeric_consistent = False
        return {
            "label": label,
            "is_numeric_claim": is_numeric,
            "numeric_consistent": numeric_consistent,
            "rationale": str(data.get("rationale", "")),
        }
    except Exception:
        label = _fallback_claim_label(claim, evidences)
        nums = _extract_numbers(claim)
        nums = [x for x in nums if not _looks_like_time_marker_number(x)]
        numeric_consistent = True
        if nums:
            ev_nums: list[str] = []
            for ev in evidences:
                ev_nums.extend(_extract_numbers(ev))
            numeric_consistent = all(n in ev_nums for n in nums) if ev_nums else False
        return {
            "label": label,
            "is_numeric_claim": bool(nums),
            "numeric_consistent": numeric_consistent,
            "rationale": "fallback",
        }


def judge_keypoint(
    *,
    keypoint: str,
    answer: str,
    evidences: list[str],
    chat_client: ChatClientLike,
    model: str | None = None,
) -> dict[str, Any]:
    try:
        data = chat_client.complete_json(
            schema_name="judge_keypoint",
            system_prompt=KEYPOINT_JUDGE_SYSTEM_PROMPT,
            user_prompt=build_keypoint_judge_user_prompt(keypoint, answer, evidences),
            model=model,
            max_tokens=900,
            temperature=0.0,
        )
        coverage = str(data.get("coverage", "")).strip().lower()
        if coverage not in {"covered", "partial", "missing"}:
            coverage = "missing"
        return {
            "coverage": coverage,
            "context_supported": bool(data.get("context_supported", False)),
            "rationale": str(data.get("rationale", "")),
        }
    except Exception:
        ans = _normalize_text(answer)
        kp = _normalize_text(keypoint)
        if kp and kp in ans:
            coverage = "covered"
        elif kp and any(token in ans for token in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,}", keypoint)[:2]):
            coverage = "partial"
        else:
            coverage = "missing"
        ctx_supported = any(kp and kp[:6] in _normalize_text(ev) for ev in evidences)
        return {
            "coverage": coverage,
            "context_supported": ctx_supported,
            "rationale": "fallback",
        }


def compute_metrics_from_counters(counters: dict[str, int]) -> dict[str, float | None]:
    total_claims = counters.get("total_claims", 0)
    total_numeric_claims = counters.get("total_numeric_claims", 0)
    total_keypoints = counters.get("total_keypoints", 0)

    def _rate(num: int, den: int) -> float | None:
        if den <= 0:
            return None
        return round(num / den, 4)

    return {
        "claim_support_rate": _rate(counters.get("supported_claims", 0), total_claims),
        "unsupported_claim_rate": _rate(counters.get("unsupported_claims", 0), total_claims),
        "contradiction_rate": _rate(counters.get("contradicted_claims", 0), total_claims),
        "numeric_consistency_rate": _rate(counters.get("supported_numeric_claims", 0), total_numeric_claims),
        "keypoint_coverage": _rate(
            counters.get("covered_keypoints", 0) + int(0.5 * counters.get("partial_keypoints", 0)),
            total_keypoints,
        ),
        "keypoint_context_recall": _rate(counters.get("keypoints_supported_by_context", 0), total_keypoints),
    }


def _mock_metrics(case_id: str) -> tuple[dict[str, float | None], dict[str, Any]]:
    rng = random.Random(f"v2::{case_id}")
    metrics = {
        "keypoint_coverage": round(rng.uniform(0.84, 0.95), 4),
        "keypoint_context_recall": round(rng.uniform(0.80, 0.96), 4),
        "claim_support_rate": round(rng.uniform(0.80, 0.96), 4),
        "unsupported_claim_rate": round(rng.uniform(0.01, 0.08), 4),
        "contradiction_rate": round(rng.uniform(0.0, 0.02), 4),
        "numeric_consistency_rate": round(rng.uniform(0.97, 0.995), 4),
    }
    artifacts = {
        "counters": {
            "total_claims": 10,
            "supported_claims": int(metrics["claim_support_rate"] * 10),
            "unsupported_claims": int(metrics["unsupported_claim_rate"] * 10),
            "contradicted_claims": int(metrics["contradiction_rate"] * 10),
            "total_numeric_claims": 4,
            "supported_numeric_claims": max(1, int(metrics["numeric_consistency_rate"] * 4)),
            "total_keypoints": 8,
            "covered_keypoints": int(metrics["keypoint_coverage"] * 8),
            "partial_keypoints": 0,
            "keypoints_supported_by_context": int(metrics["keypoint_context_recall"] * 8),
        }
    }
    return metrics, artifacts


def evaluate_case_v2(
    *,
    case_id: str,
    question: str,
    ground_truth: str,
    answer: str,
    retrieved_contexts: list[str],
    chat_client: ChatClientLike | None,
    embed_client: EmbeddingClientLike | None,
    embed_model: str,
    top_k_evidence: int = 3,
    mock_mode: bool = False,
) -> tuple[dict[str, float | None], dict[str, Any], dict[str, str]]:
    if mock_mode:
        metrics, artifacts = _mock_metrics(case_id)
        return metrics, artifacts, {}

    if chat_client is None or embed_client is None:
        raise RuntimeError("真实评估模式需要 chat_client 和 embed_client")

    metric_errors: dict[str, str] = {}
    keypoints = extract_keypoints(question=question, ground_truth=ground_truth, chat_client=chat_client)
    claims = extract_claims(answer=answer, chat_client=chat_client)
    if not claims:
        claims = _split_sentences(answer, 12)
    if not keypoints:
        keypoints = _split_sentences(ground_truth, 8)

    unique_queries = list(dict.fromkeys([*claims, *keypoints]))
    try:
        evidence_map = _build_evidence_map_batch(
            queries=unique_queries,
            contexts=retrieved_contexts,
            embed_client=embed_client,
            embed_model=embed_model,
            top_k_evidence=top_k_evidence,
        )
    except Exception as exc:
        metric_errors["embedding_retrieval"] = str(exc)
        evidence_map = {}

    counters = {
        "total_claims": 0,
        "supported_claims": 0,
        "unsupported_claims": 0,
        "contradicted_claims": 0,
        "total_numeric_claims": 0,
        "supported_numeric_claims": 0,
        "total_keypoints": 0,
        "covered_keypoints": 0,
        "partial_keypoints": 0,
        "keypoints_supported_by_context": 0,
    }

    claim_judgments: list[dict[str, Any]] = []
    for claim in claims:
        counters["total_claims"] += 1
        evidences = evidence_map.get(claim, [])
        if not evidences:
            evidences = retrieved_contexts[:top_k_evidence]

        judgment = judge_claim(claim=claim, evidences=evidences, chat_client=chat_client)
        label = judgment["label"]
        if label == "supported":
            counters["supported_claims"] += 1
        elif label == "contradicted":
            counters["contradicted_claims"] += 1
        else:
            counters["unsupported_claims"] += 1

        if judgment.get("is_numeric_claim"):
            counters["total_numeric_claims"] += 1
            if judgment.get("numeric_consistent"):
                counters["supported_numeric_claims"] += 1

        claim_judgments.append({"claim": claim, **judgment})

    keypoint_judgments: list[dict[str, Any]] = []
    for keypoint in keypoints:
        counters["total_keypoints"] += 1
        evidences = evidence_map.get(keypoint, [])
        if not evidences:
            evidences = retrieved_contexts[:top_k_evidence]

        judgment = judge_keypoint(keypoint=keypoint, answer=answer, evidences=evidences, chat_client=chat_client)
        coverage = judgment.get("coverage")
        if coverage == "covered":
            counters["covered_keypoints"] += 1
        elif coverage == "partial":
            counters["partial_keypoints"] += 1
        if judgment.get("context_supported"):
            counters["keypoints_supported_by_context"] += 1
        keypoint_judgments.append({"keypoint": keypoint, **judgment})

    metrics = compute_metrics_from_counters(counters)
    artifacts = {
        "counters": counters,
        "claim_count": len(claims),
        "keypoint_count": len(keypoints),
        "claim_judgments": claim_judgments,
        "keypoint_judgments": keypoint_judgments,
    }
    return metrics, artifacts, metric_errors


def _aggregate_metrics(
    case_results: list[CaseResultV2],
    *,
    doc_type: str | None = None,
    question_type: str | None = None,
) -> dict[str, float | None]:
    subset = [c for c in case_results if c.error is None]
    if doc_type:
        subset = [c for c in subset if c.doc_type == doc_type]
    if question_type:
        subset = [c for c in subset if c.question_type == question_type]
    out: dict[str, float | None] = {}
    for key in METRIC_KEYS_V2:
        out[key] = _safe_mean([c.metrics.get(key) for c in subset])
    return out


def build_eval_report_v2(
    *,
    layer: str,
    dataset_version: str,
    config: dict[str, Any],
    case_results: list[CaseResultV2],
    gate_result: GateResultV2,
    drift_result: DriftResultV2,
) -> EvalReportV2:
    valid = [c for c in case_results if c.error is None]
    metric_null_rates: dict[str, float] = {}
    for key in METRIC_KEYS_V2:
        if not valid:
            metric_null_rates[key] = 1.0
            continue
        null_count = sum(1 for c in valid if c.metrics.get(key) is None)
        metric_null_rates[key] = round(null_count / len(valid), 4)

    doc_types = sorted({c.doc_type for c in case_results})
    question_types = sorted({c.question_type for c in case_results})

    return EvalReportV2(
        run_id=f"{layer}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
        generated_at=datetime.now(timezone.utc).isoformat(),
        layer=layer,
        dataset_version=dataset_version,
        config=config,
        overall_metrics=_aggregate_metrics(case_results),
        by_doc_type={d: _aggregate_metrics(case_results, doc_type=d) for d in doc_types},
        by_question_type={q: _aggregate_metrics(case_results, question_type=q) for q in question_types},
        metric_null_rates=metric_null_rates,
        gate_result=gate_result.to_dict(),
        drift_result=drift_result.to_dict(),
        case_results=[c.to_dict() for c in case_results],
    )


def _merge_metric_threshold(
    metric_name: str,
    base_cfg: dict[str, Any],
    doc_override: dict[str, Any] | None,
    qt_override: dict[str, Any] | None,
) -> dict[str, float]:
    result: dict[str, float] = {}
    if isinstance(base_cfg.get("min"), (int, float)):
        result["min"] = float(base_cfg["min"])
    if isinstance(base_cfg.get("max"), (int, float)):
        result["max"] = float(base_cfg["max"])

    for source in (doc_override or {}, qt_override or {}):
        m_cfg = source.get(metric_name, {}) if isinstance(source, dict) else {}
        if not isinstance(m_cfg, dict):
            continue
        if isinstance(m_cfg.get("min"), (int, float)):
            result["min"] = max(result.get("min", float("-inf")), float(m_cfg["min"]))
        if isinstance(m_cfg.get("max"), (int, float)):
            result["max"] = min(result.get("max", float("inf")), float(m_cfg["max"]))
    return result


def _eval_threshold(metric_name: str, actual: float | None, threshold: dict[str, float]) -> str | None:
    if actual is None:
        return None
    if "min" in threshold and actual < threshold["min"]:
        return f"{metric_name}: {actual:.4f} < min {threshold['min']:.4f}"
    if "max" in threshold and actual > threshold["max"]:
        return f"{metric_name}: {actual:.4f} > max {threshold['max']:.4f}"
    return None


def check_gates_v2(report: EvalReportV2, thresholds: dict[str, Any]) -> GateResultV2:
    metric_cfg = thresholds.get("metrics", {})
    doc_overrides = thresholds.get("doc_type_overrides", {})
    qt_overrides = thresholds.get("question_type_overrides", {})

    failures: list[str] = []
    null_failures: list[str] = []
    applied: dict[str, dict[str, float]] = {}

    for key, rate in report.metric_null_rates.items():
        if rate >= 1.0:
            msg = f"{key}: null_rate=100%"
            failures.append(msg)
            null_failures.append(msg)
        elif rate > 0.10:
            msg = f"{key}: null_rate={rate:.0%} > 10%"
            failures.append(msg)
            null_failures.append(msg)

    for key in METRIC_KEYS_V2:
        base = metric_cfg.get(key, {})
        threshold = _merge_metric_threshold(key, base, None, None)
        applied[f"overall.{key}"] = threshold
        err = _eval_threshold(key, report.overall_metrics.get(key), threshold)
        if err:
            failures.append(f"overall.{err}")

    for doc_type, metrics in report.by_doc_type.items():
        for key in METRIC_KEYS_V2:
            threshold = _merge_metric_threshold(
                key,
                metric_cfg.get(key, {}),
                doc_overrides.get(doc_type, {}),
                None,
            )
            applied[f"doc:{doc_type}.{key}"] = threshold
            err = _eval_threshold(key, metrics.get(key), threshold)
            if err:
                failures.append(f"doc:{doc_type}.{err}")

    for qtype, metrics in report.by_question_type.items():
        for key in METRIC_KEYS_V2:
            threshold = _merge_metric_threshold(
                key,
                metric_cfg.get(key, {}),
                None,
                qt_overrides.get(qtype, {}),
            )
            applied[f"qt:{qtype}.{key}"] = threshold
            err = _eval_threshold(key, metrics.get(key), threshold)
            if err:
                failures.append(f"qt:{qtype}.{err}")

    return GateResultV2(
        passed=not failures,
        failures=failures,
        applied_thresholds=applied,
        null_rate_failures=null_failures,
    )


def check_drift_v2(
    current_overall: dict[str, float | None],
    baseline_data: dict[str, Any] | None,
    thresholds: dict[str, Any],
) -> DriftResultV2:
    if baseline_data is None:
        return DriftResultV2(
            enabled=True,
            baseline_available=False,
            passed=True,
            deltas={},
            failures=[],
            baseline_run_id=None,
        )

    baseline_overall = baseline_data.get("overall_metrics", {})
    drift_cfg = thresholds.get("drift_gates", {})
    failures: list[str] = []
    deltas: dict[str, float] = {}

    for key in METRIC_KEYS_V2:
        cur = current_overall.get(key)
        base = baseline_overall.get(key)
        if cur is None or base is None:
            continue
        delta = round(cur - base, 4)
        deltas[key] = delta
        delta_min_key = f"{key}_delta_min"
        delta_max_key = f"{key}_delta_max"
        if delta_min_key in drift_cfg and delta < float(drift_cfg[delta_min_key]):
            failures.append(f"{key}: delta {delta:+.4f} < {drift_cfg[delta_min_key]:+.4f}")
        if delta_max_key in drift_cfg and delta > float(drift_cfg[delta_max_key]):
            failures.append(f"{key}: delta {delta:+.4f} > {drift_cfg[delta_max_key]:+.4f}")

    return DriftResultV2(
        enabled=True,
        baseline_available=True,
        passed=not failures,
        deltas=deltas,
        failures=failures,
        baseline_run_id=baseline_data.get("run_id"),
    )
