#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
RAG 生成质量评估 CLI（基于 RAGAS）

评估四项核心指标：
  - Faithfulness        忠实度（防幻觉）
  - Answer Relevancy    答案相关性
  - Context Precision   上下文精确率
  - Context Recall      上下文召回率

使用方法：
  # 完整评估（需要 LLM API Key）
  python tests/rag_quality/run_rag_quality.py

  # CI 门控模式（失败则 exit(1)）
  python tests/rag_quality/run_rag_quality.py --gate

  # 首次运行后保存基线
  python tests/rag_quality/run_rag_quality.py --save-baseline

  # 只评估特定文档类型
  python tests/rag_quality/run_rag_quality.py --doc-type filing

  # Mock 模式（不调用真实 LLM，用于验证框架本身）
  python tests/rag_quality/run_rag_quality.py --mock

环境变量（与项目其余 LLM 配置一致）：
  LLM_API_KEY       LLM API Key（必须）
  LLM_API_BASE      API Base URL（默认 https://api.openai.com/v1）
  EVAL_LLM_MODEL    评估用模型（默认 gpt-4o-mini，建议与生产模型不同）
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── 项目根路径 ───────────────────────────────────────────────────────────────

# ── Windows 控制台 UTF-8 兼容（仅 CLI 直接运行时生效，import 时跳过避免破坏 pytest）──
def _setup_win32_utf8() -> None:
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
DEFAULT_BASELINE = EVAL_DIR / "baseline.json"
DEFAULT_OUTPUT_DIR = EVAL_DIR / "reports"

METRIC_KEYS = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]
METRIC_LABELS = {
    "faithfulness": "忠实度",
    "answer_relevancy": "答案相关性",
    "context_precision": "上下文精确率",
    "context_recall": "上下文召回率",
}


# ── 数据类 ───────────────────────────────────────────────────────────────────

@dataclass
class CaseResult:
    case_id: str
    doc_type: str
    question: str
    question_type: str = "factoid"  # factoid | list | analysis
    faithfulness: float | None = None
    answer_relevancy: float | None = None
    context_precision: float | None = None
    context_recall: float | None = None
    error: str | None = None
    metric_errors: dict = field(default_factory=dict)  # {metric_key: error_msg}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvalReport:
    run_id: str
    generated_at: str
    dataset_version: str
    doc_type_filter: str | None
    total_cases: int
    evaluated_cases: int
    error_cases: int
    overall_metrics: dict[str, float | None]
    by_doc_type: dict[str, dict[str, float | None]]
    by_question_type: dict[str, dict[str, float | None]] = field(default_factory=dict)
    metric_null_rates: dict[str, float] = field(default_factory=dict)  # {metric_key: 0~1}
    case_results: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GateResult:
    passed: bool
    failures: list[str]


@dataclass
class DriftResult:
    passed: bool
    baseline_available: bool
    failures: list[str]
    deltas: dict[str, float]


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
    if not clean:
        return None
    return round(sum(clean) / len(clean), 4)


def _extract_score(raw: Any) -> float | None:
    """
    统一解析 RAGAS 0.4.x 各指标 ascore() 的返回值。

    兼容以下返回类型：
      - float / int（直接值）
      - 对象的 .value 属性
      - 对象的 .score 属性
      - dict 的 'score' 或 'value' 键

    nan / None 均视为无效，返回 None。
    """
    import math

    def _clean(v: Any) -> float | None:
        if v is None:
            return None
        try:
            f = float(v)
            return None if math.isnan(f) else round(f, 4)
        except (TypeError, ValueError):
            return None

    # 直接数值
    if isinstance(raw, (int, float)):
        return _clean(raw)

    # 对象属性：.value 优先
    if hasattr(raw, "value"):
        result = _clean(raw.value)
        if result is not None:
            return result

    # 对象属性：.score
    if hasattr(raw, "score"):
        result = _clean(raw.score)
        if result is not None:
            return result

    # dict 键
    if isinstance(raw, dict):
        for key in ("score", "value"):
            if key in raw:
                result = _clean(raw[key])
                if result is not None:
                    return result

    return None


# ── RAGAS 配置 ───────────────────────────────────────────────────────────────

def _build_ragas_llm(api_key: str, base_url: str, model: str):
    """构建 RAGAS 0.4.x 评估专用 LLM（使用 AsyncOpenAI，ascore 内部调用 agenerate()）。"""
    try:
        from openai import AsyncOpenAI
        from ragas.llms import llm_factory
    except ImportError as e:
        raise RuntimeError(
            f"缺少依赖: {e}\n请运行: pip install 'ragas>=0.2.0' openai"
        ) from e

    async_client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    return llm_factory(model, client=async_client)


def _build_ragas_embeddings(api_key: str, base_url: str):
    """
    构建 RAGAS 0.4.x collections 指标专用 Embedding。
    使用 ragas.embeddings.OpenAIEmbeddings（modern 接口，RAGAS 原生支持）。
    默认使用 BAAI/bge-m3（当前 API 端点支持）。
    """
    try:
        from openai import AsyncOpenAI
        from ragas.embeddings import OpenAIEmbeddings

        async_client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        return OpenAIEmbeddings(client=async_client, model="BAAI/bge-m3")
    except Exception as e:
        raise RuntimeError(
            f"无法初始化 Embedding 模型: {e}\n"
            "请确认 LLM_API_KEY 和 LLM_API_BASE 已配置，且 API 端点支持 bge-m3 模型。"
        ) from e


# ── 答案生成 ─────────────────────────────────────────────────────────────────

def _generate_answer(question: str, contexts: list[str], llm_client, model: str) -> str:
    """用检索到的上下文和 LLM 生成答案（使用原生 OpenAI client）。"""
    context_text = "\n\n---\n\n".join(
        f"[文档 {i+1}]\n{ctx}" for i, ctx in enumerate(contexts)
    )
    prompt = (
        "请根据以下金融文档内容，准确、简洁地回答问题。\n"
        "只使用文档中明确提到的信息，不要添加文档中没有的内容。\n\n"
        f"文档内容：\n{context_text}\n\n"
        f"问题：{question}\n\n"
        "答案："
    )
    response = llm_client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    return (response.choices[0].message.content or "").strip()


def _generate_mock_answer(question: str, contexts: list[str], case_id: str) -> str:
    """
    Mock 答案生成（无需真实 LLM）。
    模拟三种质量：good / partial / hallucinated，用于验证评估框架本身。
    """
    rng = random.Random(case_id)
    quality = rng.choice(["good", "good", "partial"])  # 大概率生成好答案
    if quality == "good":
        # 从 contexts 中截取关键句子作为答案（模拟高质量答案）
        first_ctx = contexts[0] if contexts else ""
        sentences = [s.strip() for s in first_ctx.split("。") if len(s.strip()) > 10]
        return "。".join(sentences[:2]) + "。" if sentences else first_ctx[:100]
    elif quality == "partial":
        # 只用部分信息（模拟中等质量答案）
        return contexts[0][:80] + "..." if contexts else "信息不足，无法回答。"
    else:
        # 捏造答案（模拟幻觉，Mock 模式下不会触发）
        return f"根据分析，{question[:-1]}的结果约为100亿元，增速约为50%。"


# ── 核心评估逻辑 ─────────────────────────────────────────────────────────────

def _mock_scores(case_id: str) -> dict[str, float]:
    """生成确定性 mock 分数，用于验证框架本身（不调用任何 LLM）。"""
    rng = random.Random(case_id)
    base = rng.uniform(0.78, 0.95)
    return {
        "faithfulness":       round(rng.uniform(base - 0.05, min(base + 0.05, 1.0)), 4),
        "answer_relevancy":   round(rng.uniform(base - 0.08, min(base + 0.03, 1.0)), 4),
        "context_precision":  round(rng.uniform(base - 0.12, min(base + 0.02, 1.0)), 4),
        "context_recall":     round(rng.uniform(base - 0.08, min(base + 0.04, 1.0)), 4),
    }


def evaluate_cases(
    cases: list[dict[str, Any]],
    ragas_llm,
    ragas_embeddings,
    mock_mode: bool = False,
    llm_client=None,
    delay_seconds: int = 5,
    metric_concurrency: int = 1,
    diagnostic: bool = False,
    intra_case_delay: int = 20,
    retry_delay: int = 30,
) -> list[CaseResult]:
    """
    对每个案例运行 RAGAS 四项指标评估。

    参数：
      delay_seconds       每个 case 之间等待的秒数（默认 5），避免 RPM 限流
      metric_concurrency  每个 case 内指标的并发数（默认 1 = 串行，2~4 可加速）
      diagnostic          打印每个指标的实际 metric.name，用于排查 key 映射问题
      intra_case_delay    同一 case 内相邻指标之间的等待秒数（默认 20），防止瞬时 RPM 超限
      retry_delay         指标失败后第一次重试的等待秒数（默认 30，第二次翻倍=60s）
    """
    import time

    # ── Mock 模式 ───────────────────────────────────────────────────────────
    if mock_mode:
        results: list[CaseResult] = []
        for i, case in enumerate(cases, 1):
            print(f"  [{i:02d}/{len(cases):02d}] {case['id']} ...", end=" ", flush=True)
            scores = _mock_scores(case["id"])
            results.append(CaseResult(
                case_id=case["id"],
                doc_type=case["doc_type"],
                question=case["question"],
                question_type=case.get("question_type", "factoid"),
                **scores,
            ))
            print("✓ (mock)")
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
        raise RuntimeError(
            f"缺少 ragas 依赖: {e}\n请运行: pip install 'ragas>=0.2.0'"
        ) from e

    # P0-b：显式 (metric_key, metric_obj) 元组，禁止用 metric.name 当回填 key
    metric_definitions: list[tuple[str, Any]] = [
        ("faithfulness",       Faithfulness(llm=ragas_llm)),
        ("answer_relevancy",   AnswerRelevancy(llm=ragas_llm, embeddings=ragas_embeddings)),
        ("context_precision",  ContextPrecisionWithoutReference(llm=ragas_llm)),
        ("context_recall",     ContextRecall(llm=ragas_llm)),
    ]

    # P0-a：诊断模式 —— 打印各指标的实际 .name 属性
    if diagnostic:
        print("\n  [diagnostic] 各指标的实际 metric.name 值：")
        for key, metric in metric_definitions:
            actual_name = getattr(metric, "name", "<no .name>")
            match_flag = "✓" if actual_name == key else "⚠ 不匹配"
            print(f"    显式 key={key!r:30s}  metric.name={actual_name!r}  {match_flag}")
        print()

    results = []

    for i, case in enumerate(cases, 1):
        case_id = case["id"]
        doc_type = case["doc_type"]
        question = case["question"]
        question_type = case.get("question_type", "factoid")
        contexts = case["mock_contexts"]
        ground_truth = case["ground_truth"]

        if i > 1 and delay_seconds > 0:
            print(f"  ⏱ 等待 {delay_seconds}s 避免 RPM 限流...", flush=True)
            time.sleep(delay_seconds)

        print(f"  [{i:02d}/{len(cases):02d}] {case_id} ...", end=" ", flush=True)

        try:
            # 生成答案
            answer = _generate_answer(question, contexts, llm_client, llm_client._model)

            import asyncio
            import inspect

            all_data = {
                "user_input": question,
                "response": answer,
                "retrieved_contexts": contexts,
                "reference": ground_truth,
            }

            semaphore = asyncio.Semaphore(metric_concurrency)  # noqa: F841（metric_concurrency 保留供未来扩展）

            async def _score_all():
                # P0-b + P0-c + P0-e：显式 key、统一解析、指数退避重试
                # RPM 修复：指标真正串行执行，各指标间睡 intra_case_delay 秒
                async def _score_one(metric_key: str, metric) -> tuple[str, float | None, str | None]:
                    sig = inspect.signature(metric.ascore)
                    kwargs = {k: v for k, v in all_data.items() if k in sig.parameters}
                    last_err: str | None = None

                    # 最多重试 2 次（P0-e），退避时间由 retry_delay 控制
                    for attempt in range(3):
                        try:
                            raw = await metric.ascore(**kwargs)
                            val = _extract_score(raw)
                            if val is not None:
                                return metric_key, val, None
                            # 解析失败——不重试，直接记录
                            diag = (
                                f"_extract_score 无法解析 "
                                f"{type(raw).__name__}={repr(raw)[:120]}"
                            )
                            return metric_key, None, diag
                        except Exception as e:
                            last_err = f"{type(e).__name__}: {e}"
                            if attempt < 2:
                                wait = retry_delay * (attempt + 1)  # 30s, 60s
                                print(f"\n    ↺ {metric_key} retry {attempt+1}/2，等待 {wait}s...", end="", flush=True)
                                await asyncio.sleep(wait)

                    return metric_key, None, last_err

                # 真正串行：metrics 逐个执行，间隔 intra_case_delay 秒
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
            )
            print("✓")

        except Exception as e:
            result = CaseResult(
                case_id=case_id,
                doc_type=doc_type,
                question=question,
                question_type=question_type,
                error=str(e),
            )
            print(f"✗ {e}")

        results.append(result)

    return results


# ── 聚合与门控 ───────────────────────────────────────────────────────────────

def _aggregate_metrics(
    results: list[CaseResult],
    doc_type: str | None = None,
    question_type: str | None = None,
) -> dict[str, float | None]:
    """对指定 doc_type / question_type（或全部）的结果做平均。"""
    subset = [r for r in results if r.error is None]
    if doc_type:
        subset = [r for r in subset if r.doc_type == doc_type]
    if question_type:
        subset = [r for r in subset if r.question_type == question_type]
    return {
        key: _safe_mean([getattr(r, key) for r in subset])
        for key in METRIC_KEYS
    }


def check_gates(
    overall: dict[str, float | None],
    thresholds: dict[str, Any],
    doc_type: str | None = None,
    metric_null_rates: dict[str, float] | None = None,
    strict_null: bool = False,
    by_question_type: dict[str, dict[str, float | None]] | None = None,
) -> GateResult:
    """
    检查整体指标是否达到门控阈值。

    strict_null=True 时，任何核心指标 null_rate > 0 直接 fail（nightly 模式推荐）。
    by_question_type 不为空时，对每个 question_type 组额外应用分层阈值（P1-b）。
    """
    metric_cfg = thresholds["metrics"]
    failures: list[str] = []

    # P0-d：null_rate hard gate
    if metric_null_rates:
        for key in METRIC_KEYS:
            null_rate = metric_null_rates.get(key, 0.0)
            label = METRIC_LABELS[key]
            if strict_null and null_rate > 0:
                failures.append(
                    f"{label}({key}): null_rate={null_rate:.0%}，"
                    f"strict 模式下不允许任何 null（修复评估器后重跑）"
                )
            elif null_rate >= 1.0:
                # 100% null 无论什么模式都 fail
                failures.append(
                    f"{label}({key}): null_rate=100%，该指标完全无效"
                )

    # 整体指标门控（doc_type 级别覆盖）
    for key in METRIC_KEYS:
        if doc_type and doc_type in thresholds.get("doc_type_overrides", {}):
            override = thresholds["doc_type_overrides"][doc_type]
            min_val = override.get(key, {}).get("min", metric_cfg[key]["min"])
        else:
            min_val = metric_cfg[key]["min"]

        actual = overall.get(key)
        if actual is None:
            # null_rate gate 已覆盖，这里跳过重复报告
            pass
        elif actual < min_val:
            label = METRIC_LABELS[key]
            failures.append(f"{label}({key}): {actual:.3f} < 最低要求 {min_val}")

    # P1-b：question_type 分层阈值检查
    if by_question_type:
        qt_overrides = thresholds.get("question_type_overrides", {})
        for qt, qt_metrics in by_question_type.items():
            if qt not in qt_overrides:
                continue
            qt_override = qt_overrides[qt]
            for key in METRIC_KEYS:
                if key not in qt_override:
                    continue
                min_val = qt_override[key]["min"]
                actual = qt_metrics.get(key)
                if actual is None:
                    continue
                if actual < min_val:
                    label = METRIC_LABELS[key]
                    failures.append(
                        f"[{qt}] {label}({key}): {actual:.3f} < 分层阈值 {min_val}"
                    )

    return GateResult(passed=len(failures) == 0, failures=failures)


def check_drift(
    overall: dict[str, float | None],
    baseline_data: dict[str, Any] | None,
    thresholds: dict[str, Any],
) -> DriftResult:
    """检测指标相对基线的退步幅度。"""
    if baseline_data is None or baseline_data.get("overall_metrics", {}).get("faithfulness") is None:
        return DriftResult(passed=True, baseline_available=False, failures=[], deltas={})

    drift_gates = thresholds["drift_gates"]
    baseline_overall = baseline_data["overall_metrics"]
    failures: list[str] = []
    deltas: dict[str, float] = {}

    for key in METRIC_KEYS:
        baseline_val = baseline_overall.get(key)
        actual = overall.get(key)
        if baseline_val is None or actual is None:
            continue
        delta = actual - baseline_val
        deltas[key] = round(delta, 4)
        delta_min = drift_gates[f"{key}_delta_min"]
        if delta < delta_min:
            label = METRIC_LABELS[key]
            failures.append(
                f"{label}({key}): 退步 {delta:+.3f}，"
                f"基线={baseline_val:.3f}，当前={actual:.3f}，"
                f"允许最大退步={delta_min}"
            )

    return DriftResult(
        passed=len(failures) == 0,
        baseline_available=True,
        failures=failures,
        deltas=deltas,
    )


# ── 报告生成 ─────────────────────────────────────────────────────────────────

def build_report(
    results: list[CaseResult],
    dataset: dict[str, Any],
    doc_type_filter: str | None,
) -> EvalReport:
    """从案例结果构建完整评估报告。"""
    doc_types = ["filing", "transcript", "news"]

    # 计算每个指标的 null_rate（error case 排除在外，只看成功 case 中的 null）
    valid = [r for r in results if r.error is None]
    metric_null_rates: dict[str, float] = {}
    for key in METRIC_KEYS:
        if not valid:
            metric_null_rates[key] = 1.0
        else:
            null_count = sum(1 for r in valid if getattr(r, key) is None)
            metric_null_rates[key] = round(null_count / len(valid), 4)

    return EvalReport(
        run_id=f"rag-quality-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
        generated_at=datetime.now(timezone.utc).isoformat(),
        dataset_version=dataset.get("version", "unknown"),
        doc_type_filter=doc_type_filter,
        total_cases=len(results),
        evaluated_cases=sum(1 for r in results if r.error is None),
        error_cases=sum(1 for r in results if r.error is not None),
        overall_metrics=_aggregate_metrics(results),
        by_doc_type={dt: _aggregate_metrics(results, doc_type=dt) for dt in doc_types},
        by_question_type={
            qt: _aggregate_metrics(results, question_type=qt)
            for qt in ["factoid", "list", "analysis"]
        },
        metric_null_rates=metric_null_rates,
        case_results=[r.to_dict() for r in results],
    )


def _print_summary(
    report: EvalReport,
    thresholds: dict[str, Any],
    gate_result: GateResult,
    drift_result: DriftResult,
) -> None:
    """打印评估摘要表格。"""
    metric_cfg = thresholds["metrics"]
    sep = "─" * 70

    print(f"\n{'═' * 70}")
    print(f"  RAG 生成质量评估报告  {report.generated_at[:19]}")
    print(f"{'═' * 70}")
    print(f"  数据集版本: {report.dataset_version}  |  "
          f"总案例: {report.total_cases}  |  "
          f"成功: {report.evaluated_cases}  |  "
          f"失败: {report.error_cases}")
    if report.doc_type_filter:
        print(f"  文档类型过滤: {report.doc_type_filter}")

    print(f"\n  {'指标':<22} {'当前':>8} {'最低要求':>8} {'优秀线':>8} {'null率':>7} {'状态':>6}")
    print(f"  {sep}")
    for key in METRIC_KEYS:
        val = report.overall_metrics.get(key)
        min_val = metric_cfg[key]["min"]
        excellent = metric_cfg[key].get("excellent", "-")
        label = f"{METRIC_LABELS[key]}({key})"
        val_str = f"{val:.4f}" if val is not None else "  N/A "
        null_rate = report.metric_null_rates.get(key, 0.0)
        null_str = f"{null_rate:.0%}" if null_rate > 0 else "  0%"
        status = "✓" if (val is not None and val >= min_val) else "✗"
        print(f"  {label:<32} {val_str:>8} {min_val:>8.2f} "
              f"{(f'{excellent:.2f}' if isinstance(excellent, float) else str(excellent)):>8} "
              f"{null_str:>7} {status:>6}")

    print(f"\n  按文档类型分类：")
    print(f"  {'文档类型':<12} {'忠实度':>10} {'相关性':>10} {'上下文精':>10} {'上下文召':>10}")
    print(f"  {sep}")
    for dt in ["filing", "transcript", "news"]:
        m = report.by_doc_type.get(dt, {})
        vals = [f"{m.get(k):.3f}" if m.get(k) is not None else " N/A" for k in METRIC_KEYS]
        print(f"  {dt:<12} {vals[0]:>10} {vals[1]:>10} {vals[2]:>10} {vals[3]:>10}")

    # P1-b：按问题类型分类（附 answer_relevancy 分层阈值标注）
    qt_overrides = thresholds.get("question_type_overrides", {})
    qt_labels = {"factoid": "factoid", "list": "list", "analysis": "analysis"}
    print(f"\n  按问题类型分类（括号内为分层阈值）：")
    print(f"  {'问题类型':<12} {'忠实度':>10} {'相关性':>14} {'上下文精':>10} {'上下文召':>10}")
    print(f"  {sep}")
    for qt in ["factoid", "list", "analysis"]:
        m = report.by_question_type.get(qt, {})
        vals = [f"{m.get(k):.3f}" if m.get(k) is not None else " N/A" for k in METRIC_KEYS]
        # answer_relevancy 附加分层阈值标注
        ar_min = qt_overrides.get(qt, {}).get("answer_relevancy", {}).get("min")
        ar_tag = f"(≥{ar_min:.2f})" if ar_min is not None else ""
        ar_str = f"{vals[1]} {ar_tag}"
        print(f"  {qt_labels.get(qt, qt):<12} {vals[0]:>10} {ar_str:>14} {vals[2]:>10} {vals[3]:>10}")

    print(f"\n  漂移检测: ", end="")
    if not drift_result.baseline_available:
        print("⚪ 基线未初始化（首次运行请加 --save-baseline）")
    elif drift_result.passed:
        delta_str = "  |  ".join(
            f"{METRIC_LABELS[k]}: {v:+.3f}" for k, v in drift_result.deltas.items()
        )
        print(f"✓ 无显著退步  [{delta_str}]")
    else:
        print("✗ 检测到退步")
        for f in drift_result.failures:
            print(f"    • {f}")

    print(f"\n  门控结果: ", end="")
    if gate_result.passed:
        print("✓ 全部通过")
    else:
        print(f"✗ {len(gate_result.failures)} 项未达标")
        for f in gate_result.failures:
            print(f"    • {f}")
    print(f"{'═' * 70}\n")


# ── CLI 入口 ─────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RAG 生成质量评估（RAGAS）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--gate", action="store_true",
        help="CI 门控模式：任何指标低于阈值则 exit(1)",
    )
    parser.add_argument(
        "--save-baseline", action="store_true",
        help="将本次结果保存为新基线（覆盖 baseline.json）",
    )
    parser.add_argument(
        "--doc-type", choices=["filing", "transcript", "news"],
        help="只评估指定文档类型",
    )
    parser.add_argument(
        "--mock", action="store_true",
        help="Mock 模式：不调用真实 LLM，用于验证评估框架本身",
    )
    parser.add_argument(
        "--diagnostic-metrics", action="store_true",
        help="打印各指标的实际 metric.name 属性，用于排查 key 映射问题（不影响 CI）",
    )
    parser.add_argument(
        "--strict-null", action="store_true",
        help="严格模式：任何核心指标 null_rate > 0 直接 fail（推荐 nightly CI 使用）",
    )
    parser.add_argument(
        "--delay", type=int, default=5, metavar="SECONDS",
        help="每个 case 之间等待的秒数，避免 RPM 限流（默认 5）",
    )
    parser.add_argument(
        "--metric-concurrency", type=int, default=1, metavar="N",
        help="每个 case 内同时运行的指标数（默认 1=串行，最大 4）",
    )
    parser.add_argument(
        "--intra-case-delay", type=int, default=20, metavar="SECONDS",
        help="同一 case 内相邻指标之间的等待秒数（默认 20），防止瞬时 RPM 超限",
    )
    parser.add_argument(
        "--retry-delay", type=int, default=30, metavar="SECONDS",
        help="指标失败后第一次重试的等待秒数（默认 30，第二次翻倍=60s）",
    )
    parser.add_argument(
        "--resume", type=Path, default=None, metavar="REPORT_JSON",
        help="加载已有报告 JSON，跳过成功 case，只补跑失败 case，合并输出完整报告",
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--thresholds", type=Path, default=DEFAULT_THRESHOLDS)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--model",
        default=os.getenv("EVAL_LLM_MODEL", "gpt-4o-mini"),
        help="评估用 LLM 模型（默认 gpt-4o-mini）",
    )
    return parser.parse_args()


def main() -> None:
    _setup_win32_utf8()
    # 加载 .env 文件（项目根目录），让 LLM_API_KEY 等变量生效
    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env", override=False)
    except ImportError:
        pass  # python-dotenv 未安装时静默跳过，依赖系统环境变量

    args = _parse_args()

    # ── 加载配置 ─────────────────────────────────────────────────────────────
    print("► 加载数据集和配置...")
    dataset = _load_json(args.dataset)
    thresholds = _load_json(args.thresholds)
    baseline_data: dict[str, Any] | None = None
    if args.baseline.exists():
        baseline_data = _load_json(args.baseline)
        if baseline_data.get("overall_metrics", {}).get("faithfulness") is None:
            baseline_data = None

    # ── 过滤案例 ─────────────────────────────────────────────────────────────
    cases = dataset["cases"]
    if args.doc_type:
        cases = [c for c in cases if c["doc_type"] == args.doc_type]

    # ── Resume 模式：加载已有报告，跳过成功 case ─────────────────────────────
    resumed_results: list[CaseResult] = []
    if args.resume:
        if not args.resume.exists():
            print(f"✗ --resume 指定的报告文件不存在: {args.resume}")
            sys.exit(1)
        prev = _load_json(args.resume)
        succeeded_ids = {
            r["case_id"] for r in prev["case_results"] if r.get("error") is None
        }
        # 把已成功的 case 转回 CaseResult 对象
        for r in prev["case_results"]:
            if r.get("error") is None:
                resumed_results.append(CaseResult(
                    case_id=r["case_id"],
                    doc_type=r["doc_type"],
                    question=r["question"],
                    question_type=r.get("question_type", "factoid"),
                    faithfulness=r.get("faithfulness"),
                    answer_relevancy=r.get("answer_relevancy"),
                    context_precision=r.get("context_precision"),
                    context_recall=r.get("context_recall"),
                ))
        # 只补跑失败/未跑的 case
        pending = [c for c in cases if c["id"] not in succeeded_ids]
        skipped = len(cases) - len(pending)
        print(f"► Resume 模式：跳过 {skipped} 个已成功 case，补跑 {len(pending)} 个")
        cases = pending

    print(f"► 共 {len(cases)} 个评估案例"
          + (f"（类型过滤: {args.doc_type}）" if args.doc_type else "")
          + (f"（并发: {args.metric_concurrency}，间隔: {args.delay}s）" if not args.mock else ""))

    # ── 初始化 RAGAS 组件 ────────────────────────────────────────────────────
    if args.mock:
        print("► Mock 模式：跳过真实 LLM 初始化")
        ragas_llm = None
        ragas_embeddings = None
        llm_client = None
    else:
        api_key = os.getenv("LLM_API_KEY", "")
        base_url = os.getenv("LLM_API_BASE", "https://api.openai.com/v1")
        if not api_key:
            print("✗ 缺少 LLM_API_KEY 环境变量，请设置后重试或使用 --mock 模式")
            sys.exit(1)
        print(f"► 初始化 RAGAS LLM: {args.model} @ {base_url}")
        ragas_llm = _build_ragas_llm(api_key, base_url, args.model)
        ragas_embeddings = _build_ragas_embeddings(api_key, base_url)

        from openai import OpenAI as _OpenAI
        llm_client = _OpenAI(api_key=api_key, base_url=base_url)
        llm_client._model = args.model

    # ── 运行评估 ─────────────────────────────────────────────────────────────
    print("► 开始评估...\n")
    new_results = evaluate_cases(
        cases=cases,
        ragas_llm=ragas_llm,
        ragas_embeddings=ragas_embeddings,
        mock_mode=args.mock,
        llm_client=llm_client,
        delay_seconds=args.delay if not args.mock else 0,
        metric_concurrency=max(1, min(args.metric_concurrency, 4)),
        diagnostic=getattr(args, "diagnostic_metrics", False),
        intra_case_delay=args.intra_case_delay if not args.mock else 0,
        retry_delay=args.retry_delay,
    )

    # ── 合并 resume 已有结果 ──────────────────────────────────────────────────
    results = resumed_results + new_results
    if resumed_results:
        print(f"\n► 合并结果：{len(resumed_results)} 个已有 + {len(new_results)} 个新增 = {len(results)} 个总计")

    # ── 构建报告 ─────────────────────────────────────────────────────────────
    report = build_report(results, dataset, args.doc_type)
    gate_result = check_gates(
        report.overall_metrics,
        thresholds,
        args.doc_type,
        metric_null_rates=report.metric_null_rates,
        strict_null=getattr(args, "strict_null", False),
        by_question_type=report.by_question_type,
    )
    # 全量运行时，额外按 doc_type 分组检查各自的 override 阈值
    # （mock 模式跳过：合成分数不应触发 doc_type 严格门控）
    if args.doc_type is None and report.by_doc_type and not args.mock:
        for dt, dt_metrics in report.by_doc_type.items():
            dt_gate = check_gates(dt_metrics, thresholds, dt)
            if not dt_gate.passed:
                prefixed = [f"[{dt}] {f}" for f in dt_gate.failures]
                gate_result = GateResult(
                    passed=False,
                    failures=gate_result.failures + prefixed,
                )
    # Mock 模式下跳过 drift 检测（合成分数与真实基线必然不同）
    if args.mock:
        drift_result = DriftResult(passed=True, baseline_available=False, failures=[], deltas={})
    else:
        drift_result = check_drift(report.overall_metrics, baseline_data, thresholds)

    # ── 打印摘要 ─────────────────────────────────────────────────────────────
    _print_summary(report, thresholds, gate_result, drift_result)

    # ── 保存报告 ─────────────────────────────────────────────────────────────
    report_path = args.output_dir / f"{report.run_id}.json"
    _save_json(report.to_dict(), report_path)
    print(f"► 报告已保存: {report_path}")

    # ── 保存基线 ─────────────────────────────────────────────────────────────
    if args.save_baseline:
        baseline_payload = {
            "run_id": report.run_id,
            "generated_at": report.generated_at,
            "dataset_version": report.dataset_version,
            "note": "由 run_rag_quality.py --save-baseline 生成",
            "overall_metrics": report.overall_metrics,
            "by_doc_type": report.by_doc_type,
            "by_question_type": report.by_question_type,
        }
        _save_json(baseline_payload, args.baseline)
        print(f"► 基线已更新: {args.baseline}")

    # ── CI 门控 ──────────────────────────────────────────────────────────────
    if args.gate:
        if not gate_result.passed:
            print("✗ CI 门控未通过，终止流水线")
            sys.exit(1)
        if not drift_result.passed:
            print("✗ 检测到质量退步超出容忍范围，终止流水线")
            sys.exit(1)
        print("✓ CI 门控通过")


if __name__ == "__main__":
    main()
