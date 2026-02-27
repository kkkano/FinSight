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

# ── Windows 控制台 UTF-8 兼容 ────────────────────────────────────────────────
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
    faithfulness: float | None = None
    answer_relevancy: float | None = None
    context_precision: float | None = None
    context_recall: float | None = None
    error: str | None = None

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


# ── RAGAS 配置 ───────────────────────────────────────────────────────────────

def _build_ragas_llm(api_key: str, base_url: str, model: str):
    """构建 RAGAS 0.4.x 评估专用 LLM（使用 llm_factory，原生 OpenAI 兼容接口）。"""
    try:
        from openai import OpenAI
        from ragas.llms import llm_factory
    except ImportError as e:
        raise RuntimeError(
            f"缺少依赖: {e}\n请运行: pip install 'ragas>=0.2.0' openai"
        ) from e

    openai_client = OpenAI(api_key=api_key, base_url=base_url)
    return llm_factory(model, client=openai_client)


def _build_ragas_embeddings(api_key: str, base_url: str):
    """
    构建 RAGAS 0.4.x collections 指标专用 Embedding。
    使用 ragas.embeddings.OpenAIEmbeddings（modern 接口，RAGAS 原生支持）。
    通过 x666.me OpenAI 兼容 API 获取 text-embedding-3-small。
    """
    try:
        from openai import AsyncOpenAI
        from ragas.embeddings import OpenAIEmbeddings

        async_client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        return OpenAIEmbeddings(
            client=async_client,
            model="text-embedding-3-small",
        )
    except Exception as e:
        raise RuntimeError(
            f"无法初始化 Embedding 模型: {e}\n"
            "请确认 LLM_API_KEY 和 LLM_API_BASE 已配置，且 API 端点支持 text-embedding-3-small。"
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
    return response.choices[0].message.content.strip()


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
) -> list[CaseResult]:
    """
    对每个案例运行 RAGAS 四项指标评估。

    流程：
      1. 取 mock_contexts 作为检索上下文
      2. 生成答案（mock 或真实 LLM）
      3. 构建 SingleTurnSample
      4. 逐案例运行 RAGAS 评估（mock 模式跳过，直接返回确定性分数）
    """
    # ── Mock 模式：完全绕过 RAGAS，返回确定性分数 ──────────────────────────
    if mock_mode:
        results: list[CaseResult] = []
        for i, case in enumerate(cases, 1):
            print(f"  [{i:02d}/{len(cases):02d}] {case['id']} ...", end=" ", flush=True)
            scores = _mock_scores(case["id"])
            results.append(CaseResult(
                case_id=case["id"],
                doc_type=case["doc_type"],
                question=case["question"],
                **scores,
            ))
            print("✓ (mock)")
        return results

    # ── 真实模式：调用 RAGAS ───────────────────────────────────────────────
    try:
        from ragas import SingleTurnSample
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

    metrics = [
        Faithfulness(llm=ragas_llm),
        AnswerRelevancy(llm=ragas_llm, embeddings=ragas_embeddings),
        ContextPrecisionWithoutReference(llm=ragas_llm),
        ContextRecall(llm=ragas_llm),
    ]

    results = []

    for i, case in enumerate(cases, 1):
        case_id = case["id"]
        doc_type = case["doc_type"]
        question = case["question"]
        contexts = case["mock_contexts"]
        ground_truth = case["ground_truth"]

        print(f"  [{i:02d}/{len(cases):02d}] {case_id} ...", end=" ", flush=True)

        try:
            # 1. 生成答案
            answer = _generate_answer(question, contexts, llm_client, llm_client._model)

            # 2. 构建 RAGAS 样本
            sample = SingleTurnSample(
                user_input=question,
                response=answer,
                retrieved_contexts=contexts,
                reference=ground_truth,
            )

            # 3. 逐指标评分
            import asyncio

            async def _score_all():
                scores = {}
                for metric in metrics:
                    try:
                        score = await metric.single_turn_ascore(sample)
                        scores[metric.name] = round(float(score), 4)
                    except Exception as me:
                        scores[metric.name] = None
                        print(f"\n    ⚠ {metric.name} 评分失败: {me}")
                return scores

            scores = asyncio.run(_score_all())

            result = CaseResult(
                case_id=case_id,
                doc_type=doc_type,
                question=question,
                faithfulness=scores.get("faithfulness"),
                answer_relevancy=scores.get("answer_relevancy"),
                context_precision=scores.get("context_precision"),
                context_recall=scores.get("context_recall"),
            )
            print("✓")

        except Exception as e:
            result = CaseResult(
                case_id=case_id,
                doc_type=doc_type,
                question=question,
                error=str(e),
            )
            print(f"✗ {e}")

        results.append(result)

    return results


# ── 聚合与门控 ───────────────────────────────────────────────────────────────

def _aggregate_metrics(
    results: list[CaseResult],
    doc_type: str | None = None,
) -> dict[str, float | None]:
    """对指定 doc_type（或全部）的结果做平均。"""
    subset = [r for r in results if r.error is None]
    if doc_type:
        subset = [r for r in subset if r.doc_type == doc_type]
    return {
        key: _safe_mean([getattr(r, key) for r in subset])
        for key in METRIC_KEYS
    }


def check_gates(
    overall: dict[str, float | None],
    thresholds: dict[str, Any],
    doc_type: str | None = None,
) -> GateResult:
    """检查整体指标是否达到门控阈值。"""
    metric_cfg = thresholds["metrics"]
    failures: list[str] = []

    for key in METRIC_KEYS:
        # 如果有 doc_type 级别覆盖，使用更严格的阈值
        if doc_type and doc_type in thresholds.get("doc_type_overrides", {}):
            override = thresholds["doc_type_overrides"][doc_type]
            min_val = override.get(key, {}).get("min", metric_cfg[key]["min"])
        else:
            min_val = metric_cfg[key]["min"]

        actual = overall.get(key)
        if actual is None:
            failures.append(f"{key}: 无有效分数（全部评估失败）")
        elif actual < min_val:
            label = METRIC_LABELS[key]
            failures.append(f"{label}({key}): {actual:.3f} < 最低要求 {min_val}")

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
    return EvalReport(
        run_id=f"rag-quality-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
        generated_at=datetime.now(timezone.utc).isoformat(),
        dataset_version=dataset.get("version", "unknown"),
        doc_type_filter=doc_type_filter,
        total_cases=len(results),
        evaluated_cases=sum(1 for r in results if r.error is None),
        error_cases=sum(1 for r in results if r.error is not None),
        overall_metrics=_aggregate_metrics(results),
        by_doc_type={dt: _aggregate_metrics(results, dt) for dt in doc_types},
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

    print(f"\n  {'指标':<22} {'当前':>8} {'最低要求':>8} {'优秀线':>8} {'状态':>6}")
    print(f"  {sep}")
    for key in METRIC_KEYS:
        val = report.overall_metrics.get(key)
        min_val = metric_cfg[key]["min"]
        excellent = metric_cfg[key].get("excellent", "-")
        label = f"{METRIC_LABELS[key]}({key})"
        val_str = f"{val:.4f}" if val is not None else "  N/A "
        status = "✓" if (val is not None and val >= min_val) else "✗"
        print(f"  {label:<32} {val_str:>8} {min_val:>8.2f} "
              f"{(f'{excellent:.2f}' if isinstance(excellent, float) else str(excellent)):>8} {status:>6}")

    print(f"\n  按文档类型分类：")
    print(f"  {'文档类型':<12} {'忠实度':>10} {'相关性':>10} {'上下文精':>10} {'上下文召':>10}")
    print(f"  {sep}")
    for dt in ["filing", "transcript", "news"]:
        m = report.by_doc_type.get(dt, {})
        vals = [f"{m.get(k):.3f}" if m.get(k) is not None else " N/A" for k in METRIC_KEYS]
        print(f"  {dt:<12} {vals[0]:>10} {vals[1]:>10} {vals[2]:>10} {vals[3]:>10}")

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
    print(f"► 共 {len(cases)} 个评估案例"
          + (f"（类型过滤: {args.doc_type}）" if args.doc_type else ""))

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
    results = evaluate_cases(
        cases=cases,
        ragas_llm=ragas_llm,
        ragas_embeddings=ragas_embeddings,
        mock_mode=args.mock,
        llm_client=llm_client,
    )

    # ── 构建报告 ─────────────────────────────────────────────────────────────
    report = build_report(results, dataset, args.doc_type)
    gate_result = check_gates(report.overall_metrics, thresholds, args.doc_type)
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
