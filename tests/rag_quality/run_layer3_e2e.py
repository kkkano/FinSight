#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Layer 3：完整 LangGraph Pipeline E2E 测试（基于 RAGAS）

与 Layer 1/2 的核心区别：
  Layer 1  → mock_contexts + 极简 Prompt → 测 LLM 基础防幻觉能力
  Layer 2  → 真实 Embedding 检索 + synthesize_agent 真实 Prompt → 测检索质量
  Layer 3  → 用户问题 → 完整 LangGraph Pipeline（planner→execute→synthesize→render）
             → 从 artifacts.render_vars / draft_markdown 提取答案 → RAGAS 评估
  测的是：用户真实体验 + 整个 Pipeline 的端到端质量

测试策略：
  - 使用 GraphRunner.create()（内存 MemorySaver，不依赖外部 PostgreSQL）
  - 通过 monkeypatch 将每个 case 的 mock_contexts 注入为 execute_plan_stub 的 evidence_pool
    → 绕过真实 tool 调用（确保测试稳定可重复），同时保留完整 planner / synthesize / render 流程
  - confirmation_mode="skip" 跳过人工确认步骤
  - 从 artifacts.draft_markdown 或 artifacts.render_vars 提取最终答案文本

使用方法：
  python tests/rag_quality/run_layer3_e2e.py
  python tests/rag_quality/run_layer3_e2e.py --mock
  python tests/rag_quality/run_layer3_e2e.py --doc-type filing
  python tests/rag_quality/run_layer3_e2e.py --gate
  python tests/rag_quality/run_layer3_e2e.py --output-mode brief

环境变量（与 Layer 1/2 共用）：
  LLM_API_KEY       LLM API Key（必须，LANGGRAPH_LLM_MODEL 节点使用）
  LLM_API_BASE      API Base URL
  EVAL_LLM_MODEL    RAGAS 评估模型（默认 deepseek-ai/DeepSeek-V3）
  LANGGRAPH_LLM_MODEL       Pipeline 中 synthesize 使用的 LLM
  LANGGRAPH_SYNTHESIZE_MODE LLM / stub（默认 stub，设为 llm 启用真实 LLM synthesize）
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
import time
import unittest.mock as mock
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Windows 控制台 UTF-8 ─────────────────────────────────────────────────────
def _setup_win32_utf8() -> None:
    if sys.platform == "win32":
        import io
        if hasattr(sys.stdout, "buffer"):
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "buffer"):
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

EVAL_DIR = Path(__file__).parent
DEFAULT_DATASET = EVAL_DIR / "dataset.json"
DEFAULT_THRESHOLDS = EVAL_DIR / "thresholds.json"
DEFAULT_BASELINE_L3 = EVAL_DIR / "baseline_layer3.json"
DEFAULT_OUTPUT_DIR = EVAL_DIR / "reports"

METRIC_KEYS = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]
METRIC_LABELS = {
    "faithfulness": "忠实度",
    "answer_relevancy": "答案相关性",
    "context_precision": "上下文精确率",
    "context_recall": "上下文召回率",
}

# ── 全局测试证据注入注册表 ───────────────────────────────────────────────────
# 键：thread_id（测试专用）→ 值：{"contexts": [...], "doc_type": str, "case_id": str}
# monkeypatched execute_plan_stub 从此处读取测试上下文
_TEST_EVIDENCE_REGISTRY: dict[str, dict[str, Any]] = {}

# ── 测试用 case → ticker 映射 ──────────────────────────────────────────────
# Pipeline 的 resolve_subject → clarify 节点需要已知的 ticker 才能继续执行。
# CN_TO_TICKER 字典目前缺少 A 股个股映射，因此测试通过 ui_context.active_symbol
# 注入 ticker，使 Pipeline 跳过 clarify 进入 planner→synthesize 完整流程。
CASE_TICKER_MAP: dict[str, str] = {
    # filing — A 股个股
    "filing_maotai_revenue_2024q3":      "600519.SS",   # 贵州茅台
    "filing_catl_gross_margin_2024":     "300750.SZ",   # 宁德时代
    "filing_byd_ev_sales_2024h1":        "002594.SZ",   # 比亚迪
    "filing_paic_embedded_value_2024":   "601318.SS",   # 中国平安
    # transcript — 中概 ADR / 港股
    "transcript_alibaba_cloud_guidance": "BABA",        # 阿里巴巴
    "transcript_tencent_gaming_recovery":"0700.HK",     # 腾讯
    "transcript_meituan_profitability":  "3690.HK",     # 美团
    "transcript_jd_supply_chain":        "JD",          # 京东
    # news — 使用代表性 ticker 或指数
    "news_fed_rate_cut_astock":          "000001.SS",   # 上证指数
    "news_china_ev_export_competition":  "002594.SZ",   # 比亚迪（EV 代表）
    "news_apple_iphone16_china_sales":   "AAPL",        # 苹果
    "news_semiconductor_export_controls":"NVDA",        # 英伟达（半导体代表）
}


# ── 数据类 ───────────────────────────────────────────────────────────────────

@dataclass
class PipelineResult:
    """单次完整 LangGraph Pipeline 运行结果"""
    case_id: str
    thread_id: str
    query: str
    answer: str                     # 从 artifacts 提取的最终答案文本
    retrieved_contexts: list[str]   # 注入的 mock_contexts（用于 RAGAS 评估）
    output_mode_used: str
    nodes_visited: list[str]        # 经过的节点列表（trace 诊断）
    synth_mode: str                 # stub / llm
    error: str | None = None


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
    answer_length: int = 0          # 答案字符数（质量参考）
    nodes_visited: list[str] = field(default_factory=list)
    synth_mode: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvalReport:
    run_id: str
    layer: str
    generated_at: str
    dataset_version: str
    doc_type_filter: str | None
    output_mode: str
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
        r = _clean(raw.value)
        if r is not None:
            return r
    if hasattr(raw, "score"):
        r = _clean(raw.score)
        if r is not None:
            return r
    if isinstance(raw, dict):
        for key in ("score", "value"):
            if key in raw:
                r = _clean(raw[key])
                if r is not None:
                    return r
    return None


# ── LangGraph 测试证据注入（monkeypatch）────────────────────────────────────

async def _injected_execute_plan_stub(state: Any) -> dict[str, Any]:
    """
    Layer 3 专用 execute_plan_stub 替换实现。

    将 _TEST_EVIDENCE_REGISTRY 中预注册的 mock_contexts 转换为 evidence_pool，
    模拟真实 tool 调用完成后的 artifacts 结构，让 synthesize 节点可以正常运行。

    与真实 execute_plan_stub 的区别：
    - 不调用任何真实外部 API
    - evidence_pool 来自测试注册表，保证稳定可重复
    - 保留 RAG 相关字段占位（rag_context=[]），synthesize 节点忽略空 RAG context
    """
    thread_id = str(state.get("thread_id") or "unknown")
    test_data = _TEST_EVIDENCE_REGISTRY.get(thread_id, {})
    contexts: list[str] = test_data.get("contexts", [])
    doc_type: str = test_data.get("doc_type", "filing")
    case_id: str = test_data.get("case_id", "unknown")

    evidence_pool: list[dict[str, Any]] = [
        {
            "title": f"[L3-Test] {doc_type}_chunk_{i + 1}",
            "snippet": ctx,
            "source": f"test_{doc_type}",
            "confidence": 0.9,
            "type": doc_type,
            "id": f"test:{case_id}:{i}",
            "published_date": None,
            "url": None,
        }
        for i, ctx in enumerate(contexts)
    ]

    # 构造与真实 execute_plan_stub 兼容的 artifacts 结构
    artifacts: dict[str, Any] = {
        "evidence_pool": evidence_pool,
        "rag_context": [],          # 空 RAG context，synthesize 节点会优雅跳过
        "step_results": {},         # 无真实 tool 输出
        "agent_outputs": {},
    }

    trace = dict(state.get("trace") or {})
    trace["executor"] = {
        "type": "layer3_test_injection",
        "injected_contexts": len(contexts),
        "case_id": case_id,
        "thread_id": thread_id,
    }

    return {"artifacts": artifacts, "trace": trace}


def _extract_answer_from_state(state: dict[str, Any]) -> tuple[str, str]:
    """
    从 LangGraph 最终状态中提取答案文本。

    返回: (answer_text, synth_mode)

    synthesize 节点根据模式将答案写入不同字段：
    - LLM 模式（output_mode=brief）→ artifacts.draft_markdown
    - LLM 模式（output_mode=brief）→ artifacts.brief_data（结构化）
    - LLM 模式（output_mode=investment_report）→ artifacts.render_vars.summary/analysis
    - stub 模式（默认）→ artifacts.render_vars（确定性占位文本）
    - chat 模式 → messages 最后一条 AIMessage
    """
    artifacts = state.get("artifacts") or {}
    synth_mode = "unknown"

    # 优先级 1: draft_markdown（brief + llm 模式最完整的输出）
    draft_md = artifacts.get("draft_markdown") or ""
    if isinstance(draft_md, str) and len(draft_md.strip()) > 50:
        return draft_md.strip(), "llm_brief"

    # 优先级 2: render_vars 中的关键字段（investment_report 或 llm 模式）
    render_vars = artifacts.get("render_vars") or {}
    if isinstance(render_vars, dict):
        parts: list[str] = []
        for field_name in ["summary", "analysis", "investment_summary", "news_summary",
                           "investment_thesis", "highlights", "conclusion"]:
            val = render_vars.get(field_name, "")
            if isinstance(val, str) and val.strip():
                parts.append(val.strip())
        if parts:
            combined = "\n\n".join(parts)
            # 判断是 stub 还是 llm（stub 输出包含特定的模板标记）
            stub_markers = ["[主体]", "[操作]", "stub", "（待接入）", "STUB"]
            synth_mode = "stub" if any(m in combined for m in stub_markers) else "llm_render_vars"
            return combined, synth_mode

    # 优先级 3: brief_data（结构化 brief）
    brief_data = artifacts.get("brief_data") or {}
    if isinstance(brief_data, dict):
        parts = []
        for field_name in ["headline", "summary", "key_points", "conclusion"]:
            val = brief_data.get(field_name, "")
            if isinstance(val, str) and val.strip():
                parts.append(val.strip())
            elif isinstance(val, list):
                parts.extend(str(v) for v in val if v)
        if parts:
            return "\n".join(parts), "llm_brief_data"

    # 优先级 4: 最后一条 AIMessage（chat 模式）
    messages = state.get("messages") or []
    for msg in reversed(messages):
        if hasattr(msg, "type") and msg.type == "ai":
            content = msg.content or ""
            if isinstance(content, str) and len(content.strip()) > 20:
                return content.strip(), "chat"

    # 兜底：返回空字符串（表示 synthesize 未产生有效输出）
    return "", "empty"


def _extract_nodes_visited(state: dict[str, Any]) -> list[str]:
    """从 trace 中提取经过的节点名称列表（诊断用）。"""
    trace = state.get("trace") or {}
    events = trace.get("events") or []
    nodes: list[str] = []
    seen: set[str] = set()
    for ev in events:
        if isinstance(ev, dict):
            node = ev.get("node") or ev.get("name") or ""
            if node and node not in seen:
                seen.add(node)
                nodes.append(node)
    return nodes


# ── Mock 分数（框架验证用）──────────────────────────────────────────────────

def _mock_scores(case_id: str) -> dict[str, float]:
    rng = random.Random(case_id + "_l3")
    # Layer 3 分数分布：综合流水线，期望值介于 Layer 1 和 Layer 2 之间
    base = rng.uniform(0.70, 0.88)
    return {
        "faithfulness":      round(rng.uniform(base - 0.10, min(base + 0.05, 1.0)), 4),
        "answer_relevancy":  round(rng.uniform(base - 0.12, min(base + 0.04, 1.0)), 4),
        "context_precision": round(rng.uniform(base - 0.18, min(base + 0.03, 1.0)), 4),
        "context_recall":    round(rng.uniform(base - 0.12, min(base + 0.05, 1.0)), 4),
    }


# ── RAGAS 配置 ───────────────────────────────────────────────────────────────

def _build_ragas_llm(api_key: str, base_url: str, model: str):
    from openai import AsyncOpenAI
    from ragas.llms import llm_factory
    return llm_factory(model, client=AsyncOpenAI(api_key=api_key, base_url=base_url))


def _build_ragas_embeddings(api_key: str, base_url: str, embed_model: str):
    from openai import AsyncOpenAI
    from ragas.embeddings import OpenAIEmbeddings
    return OpenAIEmbeddings(client=AsyncOpenAI(api_key=api_key, base_url=base_url), model=embed_model)


# ── Pipeline 运行 ────────────────────────────────────────────────────────────

async def _run_pipeline_for_case(
    case: dict[str, Any],
    output_mode: str,
    ticker: str = "",
) -> PipelineResult:
    """
    为单个测试 case 运行完整 LangGraph Pipeline。

    流程：
    1. 在 _TEST_EVIDENCE_REGISTRY 注册 mock_contexts
    2. monkeypatch execute_plan_stub
    3. GraphRunner.create() 构建内存 graph
    4. runner.ainvoke() 运行完整 pipeline
    5. 提取答案文本
    6. 清理注册表
    """
    case_id = case["id"]
    question = case["question"]
    doc_type = case["doc_type"]
    contexts = case["mock_contexts"]

    # 使用确定性 thread_id（基于 case_id + 时间戳），避免 checkpoint 残留
    thread_id = f"layer3-test-{case_id}-{int(time.time())}"

    # Step 1: 注册测试证据
    _TEST_EVIDENCE_REGISTRY[thread_id] = {
        "contexts": contexts,
        "doc_type": doc_type,
        "case_id": case_id,
    }

    try:
        # Step 2 & 3: monkeypatch + 构建 graph
        with mock.patch(
            "backend.graph.nodes.execute_plan_stub.execute_plan_stub",
            side_effect=_injected_execute_plan_stub,
        ):
            # 导入必须在 patch context 内完成，确保 runner 使用 patched 版本
            from backend.graph.runner import GraphRunner
            runner = GraphRunner.create()

            # Step 4: 运行完整 pipeline
            # 注入 active_symbol 使 resolve_subject 绑定 ticker，跳过 clarify 中断
            ui_ctx: dict[str, Any] = {}
            if ticker:
                ui_ctx["active_symbol"] = ticker
            final_state = await runner.ainvoke(
                thread_id=thread_id,
                query=question,
                output_mode=output_mode,
                ui_context=ui_ctx,
                confirmation_mode="skip",   # 跳过人工确认，保证测试自动运行
            )

        # Step 5: 提取答案
        answer, synth_mode = _extract_answer_from_state(final_state)
        nodes_visited = _extract_nodes_visited(final_state)

        # DEBUG: 诊断 clarify / answer 状态
        _cl = final_state.get("clarify") or {} if isinstance(final_state, dict) else {}
        _cl_needed = _cl.get("needed") if isinstance(_cl, dict) else "?"
        _cl_reason = _cl.get("reason", "") if isinstance(_cl, dict) else ""
        import sys as _sys
        print(f"\n      [DEBUG] clarify.needed={_cl_needed}, reason={_cl_reason!r}, "
              f"answer_len={len(answer)}, answer[:120]={answer[:120]!r}",
              file=_sys.stderr, flush=True)

        return PipelineResult(
            case_id=case_id,
            thread_id=thread_id,
            query=question,
            answer=answer,
            retrieved_contexts=contexts,  # 注入的 contexts，用于 RAGAS 评估
            output_mode_used=output_mode,
            nodes_visited=nodes_visited,
            synth_mode=synth_mode,
        )

    except Exception as e:
        return PipelineResult(
            case_id=case_id,
            thread_id=thread_id,
            query=question,
            answer="",
            retrieved_contexts=contexts,
            output_mode_used=output_mode,
            nodes_visited=[],
            synth_mode="error",
            error=str(e),
        )
    finally:
        # Step 6: 清理注册表，避免测试间干扰
        _TEST_EVIDENCE_REGISTRY.pop(thread_id, None)


def _run_pipeline_sync(case: dict[str, Any], output_mode: str, ticker: str = "") -> PipelineResult:
    """同步包装器（供 evaluate_cases 调用）。"""
    return asyncio.run(_run_pipeline_for_case(case, output_mode, ticker=ticker))


# ── 核心评估逻辑 ─────────────────────────────────────────────────────────────

def evaluate_cases(
    cases: list[dict[str, Any]],
    ragas_llm,
    ragas_embeddings,
    mock_mode: bool = False,
    output_mode: str = "brief",
    delay_seconds: int = 5,
    intra_case_delay: int = 20,
    retry_delay: int = 30,
) -> list[CaseResult]:
    """
    Layer 3 评估主循环：
    1. 完整 LangGraph Pipeline 运行（含 monkeypatched execute_plan_stub）
    2. 答案提取
    3. RAGAS 四项指标评估
    """
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
                answer_length=120,
                nodes_visited=["planner", "execute_plan", "synthesize", "render"],
                synth_mode="mock",
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
        ground_truth = case["ground_truth"]

        if i > 1 and delay_seconds > 0:
            print(f"  ⏱ case 间隔 {delay_seconds}s...", flush=True)
            time.sleep(delay_seconds)

        print(f"  [{i:02d}/{len(cases):02d}] {case_id}", flush=True)

        try:
            # Step 1: 运行完整 LangGraph Pipeline
            ticker = CASE_TICKER_MAP.get(case_id, "")
            print(f"    ↳ [Pipeline] 运行完整 graph（output_mode={output_mode}, ticker={ticker}）...", end=" ", flush=True)
            pipeline_result = _run_pipeline_sync(case, output_mode, ticker=ticker)

            if pipeline_result.error:
                raise RuntimeError(f"Pipeline 运行失败: {pipeline_result.error}")

            answer = pipeline_result.answer
            if not answer or len(answer.strip()) < 10:
                # synthesize stub 模式产生的占位文本视为"有效但低质量"
                # 不报错，让 RAGAS 自然评分（忠实度和相关性会很低）
                print(f"⚠ answer 较短（synth_mode={pipeline_result.synth_mode}, len={len(answer)}）")
            else:
                print(f"✓ answer_len={len(answer)}, synth={pipeline_result.synth_mode}, "
                      f"nodes={len(pipeline_result.nodes_visited)}")

            # Step 2: RAGAS 评估
            all_data = {
                "user_input": question,
                "response": answer or f"（{case_id} 的回答内容）",  # RAGAS 不接受空字符串
                "retrieved_contexts": pipeline_result.retrieved_contexts,
                "reference": ground_truth,
            }

            import inspect

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
                            return metric_key, None, f"_extract_score 无法解析 {type(raw).__name__}"
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
                answer_length=len(answer),
                nodes_visited=pipeline_result.nodes_visited,
                synth_mode=pipeline_result.synth_mode,
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


def check_gates(
    overall: dict[str, float | None],
    thresholds: dict[str, Any],
    metric_null_rates: dict[str, float] | None = None,
) -> GateResult:
    """
    Layer 3 门控阈值：最宽松（完整 pipeline 包含 stub 噪声）。

    注意：当 LANGGRAPH_SYNTHESIZE_MODE=stub（默认）时，
    synthesize 产生的是模板占位文本而非 LLM 生成答案，
    忠实度/相关性会偏低。设置 LANGGRAPH_SYNTHESIZE_MODE=llm 可提升质量。
    """
    l3_overrides = {
        "faithfulness":      0.65,   # stub 模式下容忍较低（占位文本）
        "answer_relevancy":  0.60,
        "context_precision": 0.55,
        "context_recall":    0.60,
    }
    failures: list[str] = []

    # null-rate 硬门槛：任何指标 100% null → 直接 fail
    if metric_null_rates:
        for key in METRIC_KEYS:
            null_rate = metric_null_rates.get(key, 0.0)
            if null_rate >= 1.0:
                failures.append(f"{METRIC_LABELS[key]}({key}): null_rate=100%，该指标完全无效")

    for key in METRIC_KEYS:
        min_val = l3_overrides[key]
        actual = overall.get(key)
        if actual is not None and actual < min_val:
            failures.append(f"{METRIC_LABELS[key]}({key}): {actual:.3f} < Layer3最低要求 {min_val}")
    return GateResult(passed=len(failures) == 0, failures=failures)


def build_report(
    results: list[CaseResult],
    dataset: dict[str, Any],
    doc_type_filter: str | None,
    output_mode: str,
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
        run_id=f"layer3-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
        layer="layer3_e2e",
        generated_at=datetime.now(timezone.utc).isoformat(),
        dataset_version=dataset.get("version", "unknown"),
        doc_type_filter=doc_type_filter,
        output_mode=output_mode,
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
    gate_result: GateResult,
    layer1_baseline: dict[str, Any] | None,
    layer2_baseline: dict[str, Any] | None,
) -> None:
    sep = "─" * 76
    print(f"\n{'═' * 76}")
    print(f"  Layer 3 E2E Pipeline 测试报告  {report.generated_at[:19]}")
    print(f"{'═' * 76}")
    print(f"  数据集: {report.dataset_version}  |  output_mode={report.output_mode}  |  "
          f"总案例: {report.total_cases}  成功: {report.evaluated_cases}  失败: {report.error_cases}")

    synth_mode_hint = os.getenv("LANGGRAPH_SYNTHESIZE_MODE", "stub")
    print(f"  synthesize 模式: {synth_mode_hint}（LANGGRAPH_SYNTHESIZE_MODE）")
    if synth_mode_hint == "stub":
        print("  ⚠ stub 模式下 synthesize 输出为模板占位文本，忠实度/相关性预期偏低。")
        print("    设置 LANGGRAPH_SYNTHESIZE_MODE=llm 可提升 Layer 3 分数。")

    if report.doc_type_filter:
        print(f"  文档类型过滤: {report.doc_type_filter}")

    # 三层对比表格
    l1_overall = (layer1_baseline or {}).get("overall_metrics", {})
    l2_overall = (layer2_baseline or {}).get("overall_metrics", {})

    print(f"\n  {'指标':<26} {'Layer3':>8} {'Layer2':>8} {'Layer1':>8} {'null率':>7} {'状态':>6}")
    print(f"  {sep}")
    l3_overrides = {"faithfulness": 0.65, "answer_relevancy": 0.60, "context_precision": 0.55, "context_recall": 0.60}
    for key in METRIC_KEYS:
        val = report.overall_metrics.get(key)
        l2_val = l2_overall.get(key)
        l1_val = l1_overall.get(key)
        min_val = l3_overrides[key]
        label = f"{METRIC_LABELS[key]}({key})"
        val_str = f"{val:.4f}" if val is not None else "  N/A "
        l2_str = f"{l2_val:.4f}" if l2_val is not None else "  N/A "
        l1_str = f"{l1_val:.4f}" if l1_val is not None else "  N/A "
        null_rate = report.metric_null_rates.get(key, 0.0)
        null_str = f"{null_rate:.0%}" if null_rate > 0 else "  0%"
        status = "✓" if (val is not None and val >= min_val) else "✗"
        print(f"  {label:<32} {val_str:>8} {l2_str:>8} {l1_str:>8} {null_str:>7} {status:>6}")

    print(f"\n  按文档类型分类：")
    print(f"  {'文档类型':<12} {'忠实度':>10} {'相关性':>10} {'上下文精':>10} {'上下文召':>10}")
    print(f"  {sep}")
    for dt in ["filing", "transcript", "news"]:
        m = report.by_doc_type.get(dt, {})
        vals = [f"{m.get(k):.3f}" if m.get(k) is not None else " N/A" for k in METRIC_KEYS]
        print(f"  {dt:<12} {vals[0]:>10} {vals[1]:>10} {vals[2]:>10} {vals[3]:>10}")

    # 每个 case 的 synth_mode 统计（诊断用）
    synth_modes: dict[str, int] = {}
    for r in report.case_results:
        mode = r.get("synth_mode", "unknown")
        synth_modes[mode] = synth_modes.get(mode, 0) + 1
    if synth_modes:
        print(f"\n  Synthesize 模式分布: {synth_modes}")

    print(f"\n  门控结果（Layer 3 宽松阈值）: ", end="")
    if gate_result.passed:
        print("✓ 全部通过")
    else:
        print(f"✗ {len(gate_result.failures)} 项未达标")
        for f in gate_result.failures:
            print(f"    • {f}")

    print(f"\n  提示：如需测试真实 synthesize LLM 质量，请设置：")
    print(f"    LANGGRAPH_SYNTHESIZE_MODE=llm  LANGGRAPH_LLM_MODEL=deepseek-ai/DeepSeek-V3")
    print(f"{'═' * 76}\n")


# ── CLI 入口 ─────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Layer 3 E2E 测试：完整 LangGraph Pipeline + RAGAS 评估",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--gate", action="store_true", help="CI 门控模式：失败则 exit(1)")
    parser.add_argument("--save-baseline", action="store_true", help="将结果保存为 Layer 3 基线")
    parser.add_argument("--doc-type", choices=["filing", "transcript", "news"])
    parser.add_argument("--mock", action="store_true", help="Mock 模式：不调用真实 LLM")
    parser.add_argument("--output-mode", choices=["chat", "brief", "investment_report"],
                        default="brief", help="LangGraph output_mode（默认 brief）")
    parser.add_argument("--delay", type=int, default=5, metavar="SECONDS")
    parser.add_argument("--intra-case-delay", type=int, default=20, metavar="SECONDS")
    parser.add_argument("--retry-delay", type=int, default=30, metavar="SECONDS")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--thresholds", type=Path, default=DEFAULT_THRESHOLDS)
    parser.add_argument("--baseline-l1", type=Path, default=EVAL_DIR / "baseline.json")
    parser.add_argument("--baseline-l2", type=Path, default=EVAL_DIR / "baseline_layer2.json")
    parser.add_argument("--baseline-l3", type=Path, default=DEFAULT_BASELINE_L3)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--model", default=os.getenv("EVAL_LLM_MODEL", "deepseek-ai/DeepSeek-V3"),
                        help="RAGAS 评估用 LLM 模型")
    parser.add_argument("--embed-model", default=os.getenv("EMBED_MODEL", "BAAI/bge-m3"))
    return parser.parse_args()


def main() -> None:
    _setup_win32_utf8()
    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env", override=False)
    except ImportError:
        pass

    args = _parse_args()

    print("► [Layer 3] 加载数据集和配置...")
    dataset = _load_json(args.dataset)
    thresholds = _load_json(args.thresholds)

    # 加载 Layer 1 / Layer 2 基线（三层对比用）
    def _load_baseline(path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        data = _load_json(path)
        return data if data.get("overall_metrics", {}).get("faithfulness") is not None else None

    layer1_baseline = _load_baseline(args.baseline_l1)
    layer2_baseline = _load_baseline(args.baseline_l2)

    cases = dataset["cases"]
    if args.doc_type:
        cases = [c for c in cases if c["doc_type"] == args.doc_type]

    synth_mode_env = os.getenv("LANGGRAPH_SYNTHESIZE_MODE", "stub")
    print(f"► 共 {len(cases)} 个案例"
          + (f"（类型过滤: {args.doc_type}）" if args.doc_type else "")
          + f"  output_mode={args.output_mode}  synthesize={synth_mode_env}")

    # ── 初始化 RAGAS 组件 ────────────────────────────────────────────────────
    if args.mock:
        print("► Mock 模式：跳过 LLM 初始化")
        ragas_llm = None
        ragas_embeddings = None
    else:
        api_key = os.getenv("LLM_API_KEY", "")
        base_url = os.getenv("LLM_API_BASE", "https://api.openai.com/v1")
        if not api_key:
            print("✗ 缺少 LLM_API_KEY，请设置后重试或使用 --mock 模式")
            sys.exit(1)
        print(f"► 初始化 RAGAS LLM: {args.model} @ {base_url}")
        ragas_llm = _build_ragas_llm(api_key, base_url, args.model)
        ragas_embeddings = _build_ragas_embeddings(api_key, base_url, args.embed_model)

    # ── 运行评估 ─────────────────────────────────────────────────────────────
    print(f"► 开始 Layer 3 E2E 评估...\n"
          f"  注意：execute_plan_stub 已被 monkeypatch（注入 mock_contexts 为 evidence_pool）\n")
    results = evaluate_cases(
        cases=cases,
        ragas_llm=ragas_llm,
        ragas_embeddings=ragas_embeddings,
        mock_mode=args.mock,
        output_mode=args.output_mode,
        delay_seconds=args.delay if not args.mock else 0,
        intra_case_delay=args.intra_case_delay if not args.mock else 0,
        retry_delay=args.retry_delay,
    )

    # ── 构建报告 ─────────────────────────────────────────────────────────────
    report = build_report(results, dataset, args.doc_type, args.output_mode)
    gate_result = check_gates(report.overall_metrics, thresholds, metric_null_rates=report.metric_null_rates)
    _print_summary(report, gate_result, layer1_baseline, layer2_baseline)

    # ── 保存报告 ─────────────────────────────────────────────────────────────
    report_path = args.output_dir / f"{report.run_id}.json"
    _save_json(report.to_dict(), report_path)
    print(f"► 报告已保存: {report_path}")

    # ── 保存基线 ─────────────────────────────────────────────────────────────
    if args.save_baseline:
        _save_json({
            "run_id": report.run_id,
            "layer": "layer3_e2e",
            "generated_at": report.generated_at,
            "dataset_version": report.dataset_version,
            "output_mode": report.output_mode,
            "note": "由 run_layer3_e2e.py --save-baseline 生成",
            "overall_metrics": report.overall_metrics,
            "by_doc_type": report.by_doc_type,
        }, args.baseline_l3)
        print(f"► Layer 3 基线已保存: {args.baseline_l3}")

    # ── CI 门控 ──────────────────────────────────────────────────────────────
    if args.gate and not gate_result.passed:
        print("✗ Layer 3 CI 门控未通过，终止流水线")
        sys.exit(1)
    elif args.gate:
        print("✓ Layer 3 CI 门控通过")


if __name__ == "__main__":
    main()
