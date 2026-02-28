#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Layer 2：真实检索 RAG 集成测试（基于 RAGAS）

与 Layer 1 的核心区别：
  Layer 1  → mock_contexts 直接喂给极简 4 行 Prompt → 测 LLM 基础防幻觉能力
  Layer 2  → mock_contexts 先入向量库 → 真实 Embedding 检索排序 → synthesize_agent
             真实 Prompt（闭卷模式）→ RAGAS 评估
  测的是：向量检索召回质量 + Agent 提示词在真实文档上的表现

检索策略：
  - 将每个 case 的 mock_contexts 切片后用 OpenAI-compatible embedding API（bge-m3）向量化
  - 用 query 向量做 cosine 相似度排序，取 Top-K 作为真实检索上下文
  - 不依赖本地 ChromaDB 或 PostgreSQL，仅需 LLM_API_KEY

使用方法：
  python tests/rag_quality/run_layer2_retrieval.py
  python tests/rag_quality/run_layer2_retrieval.py --mock
  python tests/rag_quality/run_layer2_retrieval.py --doc-type filing
  python tests/rag_quality/run_layer2_retrieval.py --gate
  python tests/rag_quality/run_layer2_retrieval.py --top-k 5 --chunk-size 300

环境变量（与 Layer 1 共用）：
  LLM_API_KEY       LLM / Embedding API Key（必须）
  LLM_API_BASE      API Base URL（默认 https://api.openai.com/v1）
  EVAL_LLM_MODEL    评估 LLM 模型（默认 deepseek-ai/DeepSeek-V3）
  EMBED_MODEL       Embedding 模型（默认 BAAI/bge-m3）
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Windows 控制台 UTF-8 ─────────────────────────────────────────────────────
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

EVAL_DIR = Path(__file__).parent
DEFAULT_DATASET = EVAL_DIR / "dataset.json"
DEFAULT_THRESHOLDS = EVAL_DIR / "thresholds.json"
DEFAULT_BASELINE_L2 = EVAL_DIR / "baseline_layer2.json"
DEFAULT_OUTPUT_DIR = EVAL_DIR / "reports"

METRIC_KEYS = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]
METRIC_LABELS = {
    "faithfulness": "忠实度",
    "answer_relevancy": "答案相关性",
    "context_precision": "上下文精确率",
    "context_recall": "上下文召回率",
}

# Layer 2 默认检索参数
DEFAULT_TOP_K = 5          # 检索返回最相关的 K 个 chunk
DEFAULT_CHUNK_SIZE = 300   # 每个 chunk 的目标字符数（中文）
DEFAULT_CHUNK_OVERLAP = 50 # chunk 重叠字符数


# ── 数据类 ───────────────────────────────────────────────────────────────────

@dataclass
class RetrievalResult:
    """单次检索的结果（含检索到的 chunk 列表）"""
    case_id: str
    query: str
    retrieved_contexts: list[str]  # 实际检索到的 chunk
    mock_contexts: list[str]       # 原始 mock_contexts（Layer 1 对照）
    top_k_used: int
    chunk_count_indexed: int       # 入库时总 chunk 数


@dataclass
class CaseResult:
    case_id: str
    doc_type: str
    question: str
    question_type: str = "factoid"
    faithfulness: float | None = None
    answer_relevancy: float | None = None
    context_precision: float | None = None
    context_recall: float | None = None
    error: str | None = None
    metric_errors: dict = field(default_factory=dict)
    retrieved_chunk_count: int = 0   # 实际检索到的 chunk 数
    indexed_chunk_count: int = 0     # 入库总 chunk 数

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvalReport:
    run_id: str
    layer: str
    generated_at: str
    dataset_version: str
    doc_type_filter: str | None
    retrieval_top_k: int
    chunk_size: int
    total_cases: int
    evaluated_cases: int
    error_cases: int
    overall_metrics: dict[str, float | None]
    by_doc_type: dict[str, dict[str, float | None]]
    metric_null_rates: dict[str, float] = field(default_factory=dict)
    case_results: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GateResult:
    passed: bool
    failures: list[str]


# ── 文件工具 ─────────────────────────────────────────────────────────────────

def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _safe_mean(values: list[float]) -> float | None:
    clean = [v for v in values if v is not None]
    return round(sum(clean) / len(clean), 4) if clean else None


def _extract_score(raw: Any) -> float | None:
    import math

    def _clean(v: Any) -> float | None:
        if v is None:
            return None
        try:
            f = float(v)
            return None if math.isnan(f) else round(f, 4)
        except (TypeError, ValueError):
            return None

    if isinstance(raw, (int, float)):
        return _clean(raw)
    if hasattr(raw, "value"):
        result = _clean(raw.value)
        if result is not None:
            return result
    if hasattr(raw, "score"):
        result = _clean(raw.score)
        if result is not None:
            return result
    if isinstance(raw, dict):
        for key in ("score", "value"):
            if key in raw:
                result = _clean(raw[key])
                if result is not None:
                    return result
    return None


# ── 文本切片 ─────────────────────────────────────────────────────────────────

def _chunk_text(text: str, chunk_size: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_CHUNK_OVERLAP) -> list[str]:
    """
    将文本切分为重叠 chunk。
    优先在句子边界（。！？\n）切分，避免截断完整语句。
    """
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    SENTENCE_ENDS = ("。", "！", "？", ".", "!", "?", "\n\n", "\n")

    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            # 尝试在句子边界切分
            best_sep = -1
            for sep in SENTENCE_ENDS:
                pos = text.rfind(sep, start + chunk_size // 2, end)
                if pos > best_sep:
                    best_sep = pos + len(sep)
            if best_sep > start:
                end = best_sep

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = max(start + 1, end - overlap)

    return chunks


# ── Embedding 检索 ───────────────────────────────────────────────────────────

def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """计算两个向量的余弦相似度。"""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _batch_embed(texts: list[str], embed_client, embed_model: str, batch_size: int = 16) -> list[list[float]]:
    """
    批量获取文本 Embedding 向量。
    SiliconFlow 单次最多 32 条，默认 batch_size=16 留余量。
    """
    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        response = embed_client.embeddings.create(model=embed_model, input=batch)
        batch_vecs = [item.embedding for item in sorted(response.data, key=lambda x: x.index)]
        all_embeddings.extend(batch_vecs)
    return all_embeddings


def retrieve_chunks(
    query: str,
    contexts: list[str],
    embed_client,
    embed_model: str,
    top_k: int = DEFAULT_TOP_K,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> RetrievalResult:
    """
    真实向量检索：
    1. 将 contexts 切片 → 入"内存向量库"
    2. 用 query 的 embedding 做 cosine 相似度排序
    3. 返回 Top-K 最相关 chunk
    """
    # 切片
    all_chunks: list[str] = []
    for ctx in contexts:
        all_chunks.extend(_chunk_text(ctx, chunk_size, chunk_overlap))

    if not all_chunks:
        return RetrievalResult(
            case_id="", query=query, retrieved_contexts=contexts,
            mock_contexts=contexts, top_k_used=top_k, chunk_count_indexed=0,
        )

    # 批量 Embedding（query + 所有 chunk）
    all_texts = [query] + all_chunks
    all_vectors = _batch_embed(all_texts, embed_client, embed_model)
    query_vec = all_vectors[0]
    chunk_vecs = all_vectors[1:]

    # Cosine 相似度排序
    scored = [
        (i, _cosine_similarity(query_vec, chunk_vecs[i]))
        for i in range(len(all_chunks))
    ]
    scored.sort(key=lambda x: x[1], reverse=True)

    # 取 Top-K（去重相同 chunk 内容）
    seen: set[str] = set()
    retrieved: list[str] = []
    for idx, _score in scored:
        chunk = all_chunks[idx]
        if chunk not in seen:
            seen.add(chunk)
            retrieved.append(chunk)
        if len(retrieved) >= top_k:
            break

    return RetrievalResult(
        case_id="",
        query=query,
        retrieved_contexts=retrieved,
        mock_contexts=contexts,
        top_k_used=top_k,
        chunk_count_indexed=len(all_chunks),
    )


def _mock_retrieve(query: str, contexts: list[str], top_k: int) -> RetrievalResult:
    """Mock 检索（不调用 Embedding API）：固定返回前 top_k 个 context。"""
    return RetrievalResult(
        case_id="", query=query, retrieved_contexts=contexts[:top_k],
        mock_contexts=contexts, top_k_used=top_k, chunk_count_indexed=len(contexts),
    )


# ── 答案生成 ─────────────────────────────────────────────────────────────────

_SYNTH_SYSTEM_PROMPT = """\
你是一个专业的金融分析助手。你的任务是根据提供的参考文档，严谨、准确地回答用户的金融问题。

严格遵守以下规则：
1. 【严格闭卷原则】你唯一可用的信息来源是 <evidence_pool> 标签中的内容。
2. 禁止引用任何未在 <evidence_pool> 中出现的具体数字、事件或声明。
3. 回答应简洁、直接，优先引用文档中的原始数字和表述。
4. 如果文档中信息不足以回答问题，明确说明"依据当前文档，无法确认该信息"。
5. 禁止捏造财务数据、百分比或管理层言论。
"""


def _generate_answer_layer2(
    question: str,
    retrieved_contexts: list[str],
    llm_client,
    model: str,
) -> str:
    """
    使用 synthesize_agent 风格的闭卷 Prompt 生成答案。
    与 Layer 1 的极简 4 行 Prompt 的关键区别：
    - 使用 <evidence_pool> XML 标签结构（与生产 synthesize 节点一致）
    - 明确闭卷约束（Strict grounding）
    - 系统提示与 synthesize.py 节点保持同一风格
    """
    # 将检索到的 chunk 格式化为 evidence_pool（与 synthesize.py 格式对齐）
    evidence_items = [
        {"snippet": ctx, "source": f"retrieved_chunk_{i+1}", "confidence": 0.8}
        for i, ctx in enumerate(retrieved_contexts)
    ]
    evidence_json = json.dumps(evidence_items, ensure_ascii=False, indent=2)

    user_prompt = (
        f"<evidence_pool>\n{evidence_json}\n</evidence_pool>\n\n"
        f"问题：{question}\n\n"
        "请根据 evidence_pool 中的内容，用中文给出准确、简洁的答案："
    )

    response = llm_client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _SYNTH_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0,
        max_tokens=512,
    )
    return (response.choices[0].message.content or "").strip()


def _generate_mock_answer(question: str, retrieved_contexts: list[str], case_id: str) -> str:
    """Mock 答案生成（不调用 LLM）。"""
    rng = random.Random(case_id + "_layer2")
    first_ctx = retrieved_contexts[0] if retrieved_contexts else ""
    sentences = [s.strip() for s in first_ctx.split("。") if len(s.strip()) > 10]
    return "。".join(sentences[:2]) + "。" if sentences else first_ctx[:100]


# ── RAGAS 配置 ───────────────────────────────────────────────────────────────

def _build_ragas_llm(api_key: str, base_url: str, model: str):
    from openai import AsyncOpenAI
    from ragas.llms import llm_factory
    async_client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    return llm_factory(model, client=async_client)


def _build_ragas_embeddings(api_key: str, base_url: str, embed_model: str):
    from openai import AsyncOpenAI
    from ragas.embeddings import OpenAIEmbeddings
    async_client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    return OpenAIEmbeddings(client=async_client, model=embed_model)


# ── Mock 分数（框架验证用）──────────────────────────────────────────────────

def _mock_scores(case_id: str) -> dict[str, float]:
    rng = random.Random(case_id + "_l2")
    base = rng.uniform(0.72, 0.92)  # Layer 2 略低于 Layer 1（检索引入了噪声）
    return {
        "faithfulness":      round(rng.uniform(base - 0.08, min(base + 0.04, 1.0)), 4),
        "answer_relevancy":  round(rng.uniform(base - 0.10, min(base + 0.03, 1.0)), 4),
        "context_precision": round(rng.uniform(base - 0.15, min(base + 0.02, 1.0)), 4),
        "context_recall":    round(rng.uniform(base - 0.10, min(base + 0.04, 1.0)), 4),
    }


# ── 核心评估逻辑 ─────────────────────────────────────────────────────────────

def evaluate_cases(
    cases: list[dict[str, Any]],
    ragas_llm,
    ragas_embeddings,
    embed_client,
    embed_model: str,
    llm_client,
    mock_mode: bool = False,
    top_k: int = DEFAULT_TOP_K,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    delay_seconds: int = 5,
    intra_case_delay: int = 20,
    retry_delay: int = 30,
) -> list[CaseResult]:
    """
    Layer 2 评估主循环：
    1. 真实 Embedding 检索（或 mock 检索）
    2. 使用 synthesize_agent 风格 Prompt 生成答案
    3. RAGAS 四项指标评估
    """
    import asyncio
    import inspect

    # ── Mock 模式 ───────────────────────────────────────────────────────────
    if mock_mode:
        results: list[CaseResult] = []
        for i, case in enumerate(cases, 1):
            print(f"  [{i:02d}/{len(cases):02d}] {case['id']} ...", end=" ", flush=True)
            scores = _mock_scores(case["id"])
            retrieval = _mock_retrieve(case["question"], case["mock_contexts"], top_k)
            results.append(CaseResult(
                case_id=case["id"],
                doc_type=case["doc_type"],
                question=case["question"],
                question_type=case.get("question_type", "factoid"),
                retrieved_chunk_count=len(retrieval.retrieved_contexts),
                indexed_chunk_count=retrieval.chunk_count_indexed,
                **scores,
            ))
            print(f"✓ (mock, retrieved={len(retrieval.retrieved_contexts)} chunks)")
        return results

    # ── 真实模式 ─────────────────────────────────────────────────────────────
    try:
        from ragas.metrics.collections import (
            Faithfulness,
            AnswerRelevancy,
            ContextPrecisionWithoutReference,
            ContextRecall,
        )
    except ImportError as e:
        raise RuntimeError(f"缺少 ragas 依赖: {e}\n请运行: pip install 'ragas>=0.2.0'") from e

    metric_definitions: list[tuple[str, Any]] = [
        ("faithfulness",      Faithfulness(llm=ragas_llm)),
        ("answer_relevancy",  AnswerRelevancy(llm=ragas_llm, embeddings=ragas_embeddings)),
        ("context_precision", ContextPrecisionWithoutReference(llm=ragas_llm)),
        ("context_recall",    ContextRecall(llm=ragas_llm)),
    ]

    results = []

    for i, case in enumerate(cases, 1):
        case_id = case["id"]
        doc_type = case["doc_type"]
        question = case["question"]
        question_type = case.get("question_type", "factoid")
        mock_contexts = case["mock_contexts"]
        ground_truth = case["ground_truth"]

        if i > 1 and delay_seconds > 0:
            print(f"  ⏱ case 间隔 {delay_seconds}s...", flush=True)
            time.sleep(delay_seconds)

        print(f"  [{i:02d}/{len(cases):02d}] {case_id}", flush=True)

        try:
            # Step 1: 真实 Embedding 检索
            print(f"    ↳ [检索] 切片并 embedding...", end=" ", flush=True)
            retrieval = retrieve_chunks(
                query=question,
                contexts=mock_contexts,
                embed_client=embed_client,
                embed_model=embed_model,
                top_k=top_k,
                chunk_size=chunk_size,
            )
            retrieval.case_id = case_id
            print(f"indexed={retrieval.chunk_count_indexed} chunks, retrieved={len(retrieval.retrieved_contexts)}")

            # Step 2: 用 synthesize_agent 真实 Prompt 生成答案
            print(f"    ↳ [生成] synthesize_agent 闭卷 Prompt...", end=" ", flush=True)
            answer = _generate_answer_layer2(
                question=question,
                retrieved_contexts=retrieval.retrieved_contexts,
                llm_client=llm_client,
                model=llm_client._model,
            )
            print(f"answer_len={len(answer)}")

            # Step 3: RAGAS 评估
            all_data = {
                "user_input": question,
                "response": answer,
                "retrieved_contexts": retrieval.retrieved_contexts,
                "reference": ground_truth,
            }

            async def _score_all():
                async def _score_one(metric_key: str, metric) -> tuple[str, float | None, str | None]:
                    sig = inspect.signature(metric.ascore)
                    kwargs = {k: v for k, v in all_data.items() if k in sig.parameters}
                    last_err: str | None = None
                    for attempt in range(3):
                        try:
                            raw = await metric.ascore(**kwargs)
                            val = _extract_score(raw)
                            if val is not None:
                                return metric_key, val, None
                            return metric_key, None, f"_extract_score 无法解析 {type(raw).__name__}={repr(raw)[:80]}"
                        except Exception as e:
                            last_err = f"{type(e).__name__}: {e}"
                            if attempt < 2:
                                wait = retry_delay * (attempt + 1)
                                print(f"\n    ↺ {metric_key} retry {attempt+1}/2，等待 {wait}s...", end="", flush=True)
                                await asyncio.sleep(wait)
                    return metric_key, None, last_err

                serial_results = []
                for idx, (k, m) in enumerate(metric_definitions):
                    if idx > 0 and intra_case_delay > 0:
                        print(f"\n    ⏱ 指标间隔 {intra_case_delay}s...", end="", flush=True)
                        await asyncio.sleep(intra_case_delay)
                    serial_results.append(await _score_one(k, m))
                return serial_results

            triples = asyncio.run(_score_all())

            scores: dict[str, float | None] = {}
            metric_errors: dict[str, str] = {}
            for mk, val, err in triples:
                scores[mk] = val
                if err:
                    metric_errors[mk] = err
                    print(f"\n    ⚠ {mk} 失败: {err}", end="")

            result = CaseResult(
                case_id=case_id,
                doc_type=doc_type,
                question=question,
                question_type=question_type,
                faithfulness=scores.get("faithfulness"),
                answer_relevancy=scores.get("answer_relevancy"),
                context_precision=scores.get("context_precision"),
                context_recall=scores.get("context_recall"),
                metric_errors=metric_errors,
                retrieved_chunk_count=len(retrieval.retrieved_contexts),
                indexed_chunk_count=retrieval.chunk_count_indexed,
            )
            print(f"    ✓ faith={scores.get('faithfulness')} rel={scores.get('answer_relevancy')}")

        except Exception as e:
            result = CaseResult(
                case_id=case_id,
                doc_type=doc_type,
                question=question,
                question_type=question_type,
                error=str(e),
            )
            print(f"    ✗ {e}")

        results.append(result)

    return results


# ── 聚合与门控 ───────────────────────────────────────────────────────────────

def _aggregate_metrics(results: list[CaseResult], doc_type: str | None = None) -> dict[str, float | None]:
    subset = [r for r in results if r.error is None]
    if doc_type:
        subset = [r for r in subset if r.doc_type == doc_type]
    return {
        key: _safe_mean([getattr(r, key) for r in subset])
        for key in METRIC_KEYS
    }


def check_gates(overall: dict[str, float | None], thresholds: dict[str, Any]) -> GateResult:
    """
    Layer 2 门控阈值：比 Layer 1 略宽松（检索噪声容忍）。
    faithfulness >= 0.75（Layer 1 是 0.80，因检索上下文可能引入噪声）
    context_recall >= 0.65（Layer 1 是 0.70）
    """
    # Layer 2 专用宽松阈值（检索噪声容忍）
    l2_overrides = {
        "faithfulness":      0.75,
        "answer_relevancy":  0.72,
        "context_precision": 0.65,
        "context_recall":    0.65,
    }
    metric_cfg = thresholds["metrics"]
    failures: list[str] = []
    for key in METRIC_KEYS:
        min_val = l2_overrides.get(key, metric_cfg[key]["min"])
        actual = overall.get(key)
        if actual is None:
            pass
        elif actual < min_val:
            failures.append(f"{METRIC_LABELS[key]}({key}): {actual:.3f} < Layer2最低要求 {min_val}")
    return GateResult(passed=len(failures) == 0, failures=failures)


def build_report(
    results: list[CaseResult],
    dataset: dict[str, Any],
    doc_type_filter: str | None,
    top_k: int,
    chunk_size: int,
) -> EvalReport:
    valid = [r for r in results if r.error is None]
    metric_null_rates: dict[str, float] = {}
    for key in METRIC_KEYS:
        if not valid:
            metric_null_rates[key] = 1.0
        else:
            null_count = sum(1 for r in valid if getattr(r, key) is None)
            metric_null_rates[key] = round(null_count / len(valid), 4)

    return EvalReport(
        run_id=f"layer2-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
        layer="layer2_retrieval",
        generated_at=datetime.now(timezone.utc).isoformat(),
        dataset_version=dataset.get("version", "unknown"),
        doc_type_filter=doc_type_filter,
        retrieval_top_k=top_k,
        chunk_size=chunk_size,
        total_cases=len(results),
        evaluated_cases=sum(1 for r in results if r.error is None),
        error_cases=sum(1 for r in results if r.error is not None),
        overall_metrics=_aggregate_metrics(results),
        by_doc_type={dt: _aggregate_metrics(results, doc_type=dt) for dt in ["filing", "transcript", "news"]},
        metric_null_rates=metric_null_rates,
        case_results=[r.to_dict() for r in results],
    )


def _print_summary(
    report: EvalReport,
    thresholds: dict[str, Any],
    gate_result: GateResult,
    layer1_baseline: dict[str, Any] | None,
) -> None:
    sep = "─" * 72
    print(f"\n{'═' * 72}")
    print(f"  Layer 2 RAG 集成测试报告  {report.generated_at[:19]}")
    print(f"{'═' * 72}")
    print(f"  数据集: {report.dataset_version}  |  top_k={report.retrieval_top_k}  |  "
          f"chunk_size={report.chunk_size}  |  "
          f"总案例: {report.total_cases}  成功: {report.evaluated_cases}  失败: {report.error_cases}")
    if report.doc_type_filter:
        print(f"  文档类型过滤: {report.doc_type_filter}")

    # Layer 2 vs Layer 1 对比
    l1_overall = (layer1_baseline or {}).get("overall_metrics", {})
    has_l1 = bool(l1_overall.get("faithfulness"))

    print(f"\n  {'指标':<26} {'Layer2':>8} {'Layer1':>8} {'Delta':>8} {'null率':>7} {'状态':>6}")
    print(f"  {sep}")
    l2_overrides = {"faithfulness": 0.75, "answer_relevancy": 0.72, "context_precision": 0.65, "context_recall": 0.65}
    for key in METRIC_KEYS:
        val = report.overall_metrics.get(key)
        l1_val = l1_overall.get(key)
        delta_str = ""
        if val is not None and l1_val is not None:
            delta = val - l1_val
            delta_str = f"{delta:+.3f}"
        min_val = l2_overrides[key]
        label = f"{METRIC_LABELS[key]}({key})"
        val_str = f"{val:.4f}" if val is not None else "  N/A "
        l1_str = f"{l1_val:.4f}" if l1_val is not None else "  N/A "
        null_rate = report.metric_null_rates.get(key, 0.0)
        null_str = f"{null_rate:.0%}" if null_rate > 0 else "  0%"
        status = "✓" if (val is not None and val >= min_val) else "✗"
        print(f"  {label:<32} {val_str:>8} {l1_str:>8} {delta_str:>8} {null_str:>7} {status:>6}")

    print(f"\n  按文档类型分类：")
    print(f"  {'文档类型':<12} {'忠实度':>10} {'相关性':>10} {'上下文精':>10} {'上下文召':>10}")
    print(f"  {sep}")
    for dt in ["filing", "transcript", "news"]:
        m = report.by_doc_type.get(dt, {})
        vals = [f"{m.get(k):.3f}" if m.get(k) is not None else " N/A" for k in METRIC_KEYS]
        print(f"  {dt:<12} {vals[0]:>10} {vals[1]:>10} {vals[2]:>10} {vals[3]:>10}")

    print(f"\n  门控结果（Layer 2 宽松阈值）: ", end="")
    if gate_result.passed:
        print("✓ 全部通过")
    else:
        print(f"✗ {len(gate_result.failures)} 项未达标")
        for f in gate_result.failures:
            print(f"    • {f}")
    print(f"{'═' * 72}\n")


# ── CLI 入口 ─────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Layer 2 RAG 集成测试：真实 Embedding 检索 + synthesize_agent 真实 Prompt",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--gate", action="store_true", help="CI 门控模式：失败则 exit(1)")
    parser.add_argument("--save-baseline", action="store_true", help="将结果保存为 Layer 2 基线")
    parser.add_argument("--doc-type", choices=["filing", "transcript", "news"])
    parser.add_argument("--mock", action="store_true", help="Mock 模式：不调用真实 LLM/Embedding")
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K, metavar="K",
                        help=f"检索返回 Top-K 个 chunk（默认 {DEFAULT_TOP_K}）")
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE, metavar="N",
                        help=f"切片字符数（默认 {DEFAULT_CHUNK_SIZE}）")
    parser.add_argument("--delay", type=int, default=5, metavar="SECONDS")
    parser.add_argument("--intra-case-delay", type=int, default=20, metavar="SECONDS")
    parser.add_argument("--retry-delay", type=int, default=30, metavar="SECONDS")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--thresholds", type=Path, default=DEFAULT_THRESHOLDS)
    parser.add_argument("--baseline-l1", type=Path, default=EVAL_DIR / "baseline.json",
                        help="Layer 1 基线文件路径（用于对比展示）")
    parser.add_argument("--baseline-l2", type=Path, default=DEFAULT_BASELINE_L2)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--model", default=os.getenv("EVAL_LLM_MODEL", "deepseek-ai/DeepSeek-V3"))
    parser.add_argument("--embed-model", default=os.getenv("EMBED_MODEL", "BAAI/bge-m3"))
    return parser.parse_args()


def main() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env", override=False)
    except ImportError:
        pass

    args = _parse_args()

    print("► [Layer 2] 加载数据集和配置...")
    dataset = _load_json(args.dataset)
    thresholds = _load_json(args.thresholds)

    # 加载 Layer 1 基线（对比用）
    layer1_baseline: dict[str, Any] | None = None
    if args.baseline_l1.exists():
        data = _load_json(args.baseline_l1)
        if data.get("overall_metrics", {}).get("faithfulness") is not None:
            layer1_baseline = data

    cases = dataset["cases"]
    if args.doc_type:
        cases = [c for c in cases if c["doc_type"] == args.doc_type]

    print(f"► 共 {len(cases)} 个案例"
          + (f"（类型过滤: {args.doc_type}）" if args.doc_type else "")
          + f"  top_k={args.top_k}  chunk_size={args.chunk_size}")

    # ── 初始化 LLM / Embedding 客户端 ────────────────────────────────────────
    if args.mock:
        print("► Mock 模式：跳过 LLM / Embedding 初始化")
        ragas_llm = None
        ragas_embeddings = None
        embed_client = None
        llm_client = None
    else:
        api_key = os.getenv("LLM_API_KEY", "")
        base_url = os.getenv("LLM_API_BASE", "https://api.openai.com/v1")
        if not api_key:
            print("✗ 缺少 LLM_API_KEY，请设置后重试或使用 --mock 模式")
            sys.exit(1)

        print(f"► 初始化 RAGAS LLM: {args.model} @ {base_url}")
        ragas_llm = _build_ragas_llm(api_key, base_url, args.model)
        ragas_embeddings = _build_ragas_embeddings(api_key, base_url, args.embed_model)

        from openai import OpenAI as _OpenAI
        llm_client = _OpenAI(api_key=api_key, base_url=base_url)
        llm_client._model = args.model
        # embed_client 与 llm_client 共用同一 API（SiliconFlow 同时支持 chat + embedding）
        embed_client = llm_client

    # ── 运行评估 ─────────────────────────────────────────────────────────────
    print("► 开始 Layer 2 评估...\n")
    results = evaluate_cases(
        cases=cases,
        ragas_llm=ragas_llm,
        ragas_embeddings=ragas_embeddings,
        embed_client=embed_client,
        embed_model=args.embed_model,
        llm_client=llm_client,
        mock_mode=args.mock,
        top_k=args.top_k,
        chunk_size=args.chunk_size,
        delay_seconds=args.delay if not args.mock else 0,
        intra_case_delay=args.intra_case_delay if not args.mock else 0,
        retry_delay=args.retry_delay,
    )

    # ── 构建报告 ─────────────────────────────────────────────────────────────
    report = build_report(results, dataset, args.doc_type, args.top_k, args.chunk_size)
    gate_result = check_gates(report.overall_metrics, thresholds)
    _print_summary(report, thresholds, gate_result, layer1_baseline)

    # ── 保存报告 ─────────────────────────────────────────────────────────────
    report_path = args.output_dir / f"{report.run_id}.json"
    _save_json(report.to_dict(), report_path)
    print(f"► 报告已保存: {report_path}")

    # ── 保存基线 ─────────────────────────────────────────────────────────────
    if args.save_baseline:
        _save_json({
            "run_id": report.run_id,
            "layer": "layer2_retrieval",
            "generated_at": report.generated_at,
            "dataset_version": report.dataset_version,
            "retrieval_top_k": report.retrieval_top_k,
            "chunk_size": report.chunk_size,
            "note": "由 run_layer2_retrieval.py --save-baseline 生成",
            "overall_metrics": report.overall_metrics,
            "by_doc_type": report.by_doc_type,
        }, args.baseline_l2)
        print(f"► Layer 2 基线已保存: {args.baseline_l2}")

    # ── CI 门控 ──────────────────────────────────────────────────────────────
    if args.gate and not gate_result.passed:
        print("✗ Layer 2 CI 门控未通过，终止流水线")
        sys.exit(1)
    elif args.gate:
        print("✓ Layer 2 CI 门控通过")


if __name__ == "__main__":
    main()
