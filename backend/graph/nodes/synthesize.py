# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

from langchain_core.messages import HumanMessage

from backend.graph.intent_contract import is_research_compare_contract
from backend.graph.nodes.compare_gate import (
    is_compare_operation,
    should_render_compare,
)
from backend.graph.event_bus import emit_event
from backend.graph.failure import append_failure, build_runtime, utc_now_iso
from backend.graph.json_utils import json_dumps_safe
from backend.graph.preference_timeouts import timeout_seconds_from_state
from backend.graph.state import GraphState
from backend.graph.synthesis.morning_brief import (
    _extract_brief_headline,
    _synthesize_morning_brief_data,
)
from backend.graph.synthesis.narrative import (
    _skill_perspective_block,
    generate_narrative_draft,
)
from backend.graph.synthesis.normalization import (
    _DISALLOWED_SNIPPET_MARKERS,
    _DISCLAIMER_PHRASES,
    _FUTURE_DATE_PHRASE,
    _FUTURE_EVENT_VERBS,
    _HALLUCINATION_EVENT_PATTERNS,
    _HALLUCINATION_SAFE_PLACEHOLDER,
    _claim_supported_by_evidence,
    _clamp_int,
    _coerce_payload_to_strings,
    _env_bool,
    _env_int,
    _env_str,
    _extract_json_object,
    _format_conversation_history_for_synth,
    _format_memory_context_for_synth,
    _format_risks,
    _is_deep_research_run,
    _normalize_for_match,
    _normalize_llm_section_line,
    _sanitize_llm_section,
    _sanitize_user_facing_markdown,
    _scrub_unverified_future_claims,
    _section_limits,
)
from backend.graph.synthesis.structured_orchestration import (
    prepare_chat_task_contract,
    prepare_opinion_synthesis,
    synthesize_structured_report,
)
from backend.report.verifier import (  # WP3-T4 verifier 搬家回接
    _apply_verifier_redactions,
    _compute_unresolved_unsupported_claims,
    _contains_claim_after_redaction,
    _normalize_verifier_claims,
    _run_deep_report_verifier,
)
from backend.services.llm_retry import LLMCallContext, ainvoke_configured_llm, is_rate_limit_error

logger = logging.getLogger(__name__)

_REPORT_SYNTHESIS_MAX_REQUEST_TIMEOUT_SEC = 120
_REPORT_SYNTHESIS_MAX_ACQUIRE_TIMEOUT_SEC = 45
_REPORT_SYNTHESIS_MAX_ATTEMPTS = 1
_REPORT_SYNTHESIS_SDK_MAX_RETRIES = 0


def _stub_render_vars(state: GraphState) -> dict[str, str]:
    """WP3-T4 拆分：实现已迁 backend/graph/render_vars（对拍测试守护零行为）。"""
    from backend.graph.render_vars import build_render_vars

    return build_render_vars(state)


async def _generate_narrative_draft(
    state: GraphState,
    render_vars: dict[str, str],
    trace: dict[str, Any],
) -> tuple[str, dict[str, Any] | None]:
    """兼容入口：依赖从本模块注入，以保留测试与调用方 monkeypatch 语义。"""
    return await generate_narrative_draft(
        state,
        render_vars,
        trace,
        emit_event_fn=emit_event,
        ainvoke_fn=ainvoke_configured_llm,
        verifier_fn=_run_deep_report_verifier,
        is_rate_limit_error_fn=is_rate_limit_error,
    )


async def synthesize(state: GraphState) -> dict:
    """
    Phase 4.4 Synthesize node.

    Modes:
    - LANGGRAPH_SYNTHESIZE_MODE=llm (default): LLM fills render_vars JSON; validate; fallback to stub
    - LANGGRAPH_SYNTHESIZE_MODE=stub: deterministic render_vars
    - LANGGRAPH_SYNTHESIZE_MODE=llm: LLM fills render_vars JSON; validate; fallback to stub
    - LANGGRAPH_SYNTHESIZE_MODE=narrative: LLM writes full markdown report; render_vars kept for cards

    Mode resolution (2026-05-03 fix for "答非所问"):
    - The ``narrative`` mode (LLM writes a 5-section markdown report) only
      applies when ``output_mode == 'investment_report'`` (user explicitly
      asked for a report, e.g. clicked 「生成研报」or said 「研报」).
    - For ``brief`` / ``chat`` output modes (the default for casual Q&A like
      「今天微软什么价格」), narrative is downgraded to ``llm`` so the answer
      remains natural without triggering a full report.
    - ``stub`` and ``llm`` modes are NOT downgraded — both already produce
      compact ``render_vars`` for the brief template, no length explosion.
    - Multi-task chat/brief plans stay in compact LLM synthesis unless the
      caller explicitly sets ``LANGGRAPH_SYNTHESIZE_MODE=stub``. Report mode
      can still choose narrative for explicit reports.
    """
    env_mode = _env_str("LANGGRAPH_SYNTHESIZE_MODE", "llm").lower()
    output_mode = state.get("output_mode") or "brief"
    structured_synthesis_mode = _env_str("FINSIGHT_STRUCTURED_SYNTHESIS", "on").lower()
    if structured_synthesis_mode not in {"off", "shadow", "on"}:
        structured_synthesis_mode = "on"
    _ready_tasks_raw = state.get("tasks")
    _ready_tasks = _ready_tasks_raw if isinstance(_ready_tasks_raw, list) else []
    _op_dict = state.get("operation") if isinstance(state.get("operation"), dict) else {}
    _op_name_for_mode = str(_op_dict.get("name") or "").strip().lower()
    _is_pure_compare = _op_name_for_mode == "compare" and len(_ready_tasks) <= 2
    _multi_task_force_stub = (
        output_mode == "investment_report"
        and env_mode == "narrative"
        and len(_ready_tasks) >= 2
        and not _is_pure_compare
    )
    _brief_router_task_graph = (
        output_mode == "brief"
        and env_mode == "llm"
        and bool(_ready_tasks)
        and all(
            isinstance(task, dict)
            and str(task.get("reason") or "").strip()
            in {
                "conversation_router_task_hint",
                "conversation_router_task_hint_support",
                "multi_ticker_compare",
                "compare_subtask",
                "ticker_or_alias",
                "representative_basket_qa",
            }
            for task in _ready_tasks
        )
    )

    if _multi_task_force_stub:
        mode = "stub"
        logger.info(
            "[Synthesize] Multi-task plan detected (%d tasks); forcing stub mode "
            "so render_stub._build_multitask_markdown can render per-task sections "
            "(env_mode=%s, output_mode=%s)",
            len(_ready_tasks),
            env_mode,
            output_mode,
        )
    elif _brief_router_task_graph:
        mode = "stub"
        logger.info(
            "[Synthesize] brief router task graph detected; using deterministic render_vars for latency"
        )
    elif env_mode == "narrative" and output_mode != "investment_report":
        mode = "llm"
        logger.info(
            "[Synthesize] narrative downgraded to llm (output_mode=%s ≠ investment_report); "
            "narrative reserved for explicit deep-report requests only",
            output_mode,
        )
    else:
        mode = env_mode
    trace = state.get("trace") or {}
    synth_started_at = time.perf_counter()

    if os.getenv("QUERY_COVERAGE_ENABLED", "true").lower() in {"1", "true", "yes", "on"}:
        try:
            from backend.research.query_coverage import build_answer_targets, evaluate_coverage

            current_artifacts = dict(state.get("artifacts") or {})
            if not isinstance(current_artifacts.get("query_coverage"), dict):
                targets = build_answer_targets(state)
                current_artifacts["query_coverage"] = evaluate_coverage(
                    current_artifacts.get("evidence_ledger") or {},
                    targets,
                )
                state = {**state, "artifacts": current_artifacts}  # type: ignore[assignment]
                trace.setdefault("query_coverage", {})["target_count"] = len(targets)
        except Exception as exc:
            logger.info("[Synthesize] query coverage skipped: %s", exc)

    await emit_event(
        {
            "type": "pipeline_stage",
            "stage": "synthesizing",
            "status": "start",
            "message": "Synthesize started",
            "timestamp": utc_now_iso(),
        }
    )

    async def _emit_synth_stage_done(*, status: str, message: str, error: str | None = None) -> None:
        payload: dict[str, Any] = {
            "type": "pipeline_stage",
            "stage": "synthesizing",
            "status": status,
            "message": message,
            "duration_ms": int((time.perf_counter() - synth_started_at) * 1000),
            "timestamp": utc_now_iso(),
        }
        if error:
            payload["error"] = str(error)[:300]
        await emit_event(payload)

    # ── Morning brief: deterministic structured synthesis (ADR-P1-001, zero LLM) ──
    _op_raw = state.get("operation") or {}
    _op_name = _op_raw.get("name") if isinstance(_op_raw, dict) else None
    if _op_name == "morning_brief":
        brief_result = _synthesize_morning_brief_data(state)
        trace.update({
            "synthesize_runtime": {
                **build_runtime(mode="morning_brief_deterministic", fallback=False),
                "keys": ["brief_data", "draft_markdown"],
            }
        })
        merged_artifacts = {
            **(state.get("artifacts") or {}),
            "brief_data": brief_result["brief_data"],
            "draft_markdown": brief_result["draft_markdown"],
            "render_vars": {},
        }
        await _emit_synth_stage_done(status="done", message="Morning brief synthesized (deterministic)")
        return {"artifacts": merged_artifacts, "trace": trace}

    chat_task_contract = None
    if output_mode in {"chat", "brief"}:
        state, chat_task_contract = prepare_chat_task_contract(state, trace)

    # 深度报告只产生结构化 draft；Markdown 所有权属于 render_node。
    if output_mode == "investment_report" and structured_synthesis_mode in {"shadow", "on"}:
        state, structured_result = await synthesize_structured_report(
            state,
            trace,
            structured_synthesis_mode=structured_synthesis_mode,
            env_mode=env_mode,
        )
        if structured_result is not None:
            await _emit_synth_stage_done(status="done", message="Research synthesis draft completed")
            return structured_result

    if output_mode in {"chat", "brief"}:
        state = await prepare_opinion_synthesis(
            state,
            chat_task_contract,
            structured_synthesis_mode=structured_synthesis_mode,
            env_mode=env_mode,
        )

    # ── Emit decision_note when compare intent has no evidence ──
    # should_render_compare() now requires BOTH operation=compare AND valid
    # tool evidence.  When evidence is absent, the downstream _stub_render_vars
    # / LLM path will naturally degrade to multi-asset QA.  We emit a note
    # here so the frontend can surface the reason once, before mode branching.
    research_compare_contract = is_research_compare_contract(state.get("intent_contract") if isinstance(state.get("intent_contract"), dict) else None)
    if is_compare_operation(state) and not should_render_compare(state) and not research_compare_contract:
        await emit_event(
            {
                "type": "decision_note",
                "scope": "synthesize",
                "title": "Compare evidence missing — degraded to QA",
                "reason": "operation=compare but get_performance_comparison returned no valid data",
                "code": "compare_evidence_missing",
                "impact": "Using standard multi-asset QA template instead of comparison template",
                "timestamp": utc_now_iso(),
            }
        )

    # ── narrative mode: LLM writes full markdown report; render_vars kept for cards ──
    if mode == "narrative":
        logger.info("[Synthesize] Running in NARRATIVE mode — LLM writes full report draft")
        render_vars = _stub_render_vars(state)

        draft_markdown, verifier_result = await _generate_narrative_draft(state, render_vars, trace)
        verifier_claims = (
            verifier_result.get("unsupported_claims")
            if isinstance(verifier_result, dict)
            else []
        )
        unresolved_verifier_claims = (
            verifier_result.get("unresolved_unsupported_claims")
            if isinstance(verifier_result, dict)
            else []
        )
        synth_runtime: dict[str, Any] = {
            **build_runtime(mode="narrative", fallback=not bool(draft_markdown)),
            "keys": sorted(render_vars.keys()),
        }
        if isinstance(verifier_result, dict):
            synth_runtime["verifier_enabled"] = bool(verifier_result.get("enabled"))
            synth_runtime["verifier_checked"] = bool(verifier_result.get("checked"))
            synth_runtime["verifier_unsupported_count"] = (
                len(verifier_claims) if isinstance(verifier_claims, list) else 0
            )
            synth_runtime["verifier_unresolved_unsupported_count"] = (
                len(unresolved_verifier_claims) if isinstance(unresolved_verifier_claims, list) else 0
            )

        trace.update({"synthesize_runtime": synth_runtime})
        artifacts = {**(state.get("artifacts") or {}), "render_vars": render_vars}
        if draft_markdown:
            draft_markdown = _sanitize_user_facing_markdown(draft_markdown)
            artifacts["draft_markdown"] = draft_markdown
        if isinstance(verifier_result, dict):
            artifacts["verifier_result"] = verifier_result
        if isinstance(verifier_claims, list) and verifier_claims:
            await emit_event(
                {
                    "type": "decision_note",
                    "scope": "verifier",
                    "title": "Deep report verifier redactions",
                    "reason": "Detected unsupported factual claims and redacted them.",
                    "impact": f"unsupported_claims={len(verifier_claims)}",
                    "timestamp": utc_now_iso(),
                }
            )
        await _emit_synth_stage_done(status="done", message="Synthesize completed")
        return {"artifacts": artifacts, "trace": trace}

    # ── stub mode (default): deterministic render_vars ──
    raw_tasks = state.get("tasks")
    ready_tasks = [
        task for task in (raw_tasks if isinstance(raw_tasks, list) else [])
        if isinstance(task, dict) and str(task.get("status") or "ready").strip().lower() != "blocked"
    ]
    ready_task_operations = {
        str((task.get("operation") or {}).get("name") or "").strip().lower()
        for task in ready_tasks
        if isinstance(task.get("operation"), dict)
    }
    chat_brief_low_latency_ops = bool(ready_task_operations) and ready_task_operations.issubset({"price", "technical"}) and all(
        str(task.get("subject_type") or "").strip().lower() in {"company", "index", "crypto", "fund"}
        for task in ready_tasks
    )
    if mode == "llm" and output_mode in {"chat", "brief"} and ready_tasks and chat_brief_low_latency_ops:
        render_vars = _stub_render_vars(state)
        trace.update(
            {
                "synthesize_runtime": {
                    **build_runtime(mode="task_graph_stub", fallback=False),
                    "reason": "quote_or_technical_uses_short_task_graph_renderer",
                    "keys": sorted(render_vars.keys()),
                }
            }
        )
        await _emit_synth_stage_done(status="done", message="Synthesize completed in task-graph mode")
        return {"artifacts": {**(state.get("artifacts") or {}), "render_vars": render_vars}, "trace": trace}

    if mode != "llm":
        logger.info("[Synthesize] Running in STUB mode (set LANGGRAPH_SYNTHESIZE_MODE=llm for LLM synthesis)")
        render_vars = _stub_render_vars(state)
        trace.update(
            {
                "synthesize_runtime": {
                    **build_runtime(mode="stub", fallback=False),
                    "keys": sorted(render_vars.keys()),
                }
            }
        )
        await _emit_synth_stage_done(status="done", message="Synthesize completed in stub mode")
        return {"artifacts": {**(state.get("artifacts") or {}), "render_vars": render_vars}, "trace": trace}

    # ── llm mode: LLM fills render_vars JSON ──
    llm_limits = {
        "request_timeout": _env_int("LANGGRAPH_SYNTHESIZE_TIMEOUT_SEC", 150),
        "max_tokens": _env_int("LANGGRAPH_SYNTHESIZE_MAX_TOKENS", 3000),
        "max_attempts": _env_int("LANGGRAPH_SYNTHESIZE_MAX_ATTEMPTS", 2),
        "acquire_timeout": _env_int("LANGGRAPH_SYNTHESIZE_ACQUIRE_TIMEOUT_SEC", 120),
    }
    if output_mode == "investment_report":
        llm_limits = {
            "request_timeout": _env_int("LANGGRAPH_SYNTHESIZE_REPORT_TIMEOUT_SEC", 180),
            "max_tokens": _env_int("LANGGRAPH_SYNTHESIZE_REPORT_MAX_TOKENS", 6000),
            "max_attempts": _env_int("LANGGRAPH_SYNTHESIZE_REPORT_MAX_ATTEMPTS", 1),
            "acquire_timeout": _env_int("LANGGRAPH_SYNTHESIZE_REPORT_ACQUIRE_TIMEOUT_SEC", 60),
        }
    preferred_timeout = timeout_seconds_from_state(state)
    if preferred_timeout is not None:
        llm_limits["request_timeout"] = int(preferred_timeout)
        llm_limits["acquire_timeout"] = int(min(float(llm_limits["acquire_timeout"]), preferred_timeout))
    llm_create_extra: dict[str, Any] = {}
    if output_mode == "investment_report":
        llm_limits["request_timeout"] = _clamp_int(
            int(llm_limits["request_timeout"]),
            minimum=1,
            maximum=_REPORT_SYNTHESIS_MAX_REQUEST_TIMEOUT_SEC,
        )
        llm_limits["max_attempts"] = _clamp_int(
            int(llm_limits["max_attempts"]),
            minimum=1,
            maximum=_REPORT_SYNTHESIS_MAX_ATTEMPTS,
        )
        llm_limits["acquire_timeout"] = _clamp_int(
            int(llm_limits["acquire_timeout"]),
            minimum=1,
            maximum=_REPORT_SYNTHESIS_MAX_ACQUIRE_TIMEOUT_SEC,
        )
        llm_limits["sdk_max_retries"] = _REPORT_SYNTHESIS_SDK_MAX_RETRIES
        llm_create_extra["max_retries"] = _REPORT_SYNTHESIS_SDK_MAX_RETRIES
    try:
        from backend.llm_config import get_endpoint_manager

        get_endpoint_manager()
        _synth_temp = float(os.getenv("LANGGRAPH_SYNTHESIZE_TEMPERATURE", "0.2"))
        call_context = LLMCallContext.create(
            stage="synthesize",
            agent="synthesizer",
            layer="synthesis",
            max_provider_attempts=int(llm_limits["max_attempts"]),
        )
    except Exception as exc:
        render_vars = _stub_render_vars(state)
        append_failure(
            trace,
            node="synthesize",
            stage="llm_init",
            error=str(exc),
            fallback="synthesize_stub",
            retryable=False,
        )
        trace.update(
            {
                "synthesize_runtime": build_runtime(
                    mode="llm",
                    fallback=True,
                    reason=f"llm_unavailable: {exc}",
                    retry_attempts=0,
                )
                | {"llm_limits": llm_limits}
            }
        )
        await _emit_synth_stage_done(
            status="error",
            message="Synthesize LLM unavailable, fallback emitted",
            error=str(exc),
        )
        return {"artifacts": {**(state.get("artifacts") or {}), "render_vars": render_vars}, "trace": trace}

    subject = state.get("subject") or {}
    operation = state.get("operation") or {}
    output_mode = state.get("output_mode") or "brief"
    artifacts = state.get("artifacts") or {}
    evidence_pool = artifacts.get("evidence_pool") if isinstance(artifacts, dict) else None
    rag_context = artifacts.get("rag_context") if isinstance(artifacts, dict) else None
    step_results = artifacts.get("step_results") if isinstance(artifacts, dict) else None
    evidence_ledger = artifacts.get("evidence_ledger") if isinstance(artifacts, dict) else None
    query_coverage = artifacts.get("query_coverage") if isinstance(artifacts, dict) else None
    debate = artifacts.get("debate") if isinstance(artifacts, dict) else None

    # Build separated evidence sections for structured prompt
    evidence_pool_list = evidence_pool if isinstance(evidence_pool, list) else []
    rag_context_list = rag_context if isinstance(rag_context, list) else []

    inputs = {
        "query": state.get("query") or "",
        "subject": subject,
        "operation": operation,
        "output_mode": output_mode,
        "conversation_router": (state.get("trace") or {}).get("conversation_router") if isinstance(state.get("trace"), dict) else {},
        "step_results": step_results if isinstance(step_results, dict) else {},
        "evidence_ledger": evidence_ledger if isinstance(evidence_ledger, dict) else {},
        "query_coverage": query_coverage if isinstance(query_coverage, dict) else {},
        "debate": debate if isinstance(debate, dict) else {},
    }

    # Format evidence sections with XML tags
    realtime_section = ""
    if evidence_pool_list:
        realtime_section = "<realtime_evidence>\n" + json_dumps_safe(evidence_pool_list[:20], ensure_ascii=False, indent=2) + "\n</realtime_evidence>\n"

    historical_section = ""
    if rag_context_list:
        historical_section = "<historical_knowledge>\n" + json_dumps_safe(rag_context_list[:20], ensure_ascii=False, indent=2) + "\n</historical_knowledge>\n"

    evidence_rules = ""
    if realtime_section or historical_section:
        evidence_rules = """<evidence_priority_rules>
1. 实时数据与历史数据冲突时，以实时数据为准
2. 引用历史数据时必须标注数据时间（如"根据 2025 Q3 财报..."）
3. 无法确认时效性的数据需注明"截至某日期"
</evidence_priority_rules>
"""

    synth_conversation_history = _format_conversation_history_for_synth(state)
    synth_memory_context = _format_memory_context_for_synth(state)
    current_date = utc_now_iso()[:10]
    llm_grounding_text = "\n".join(
        part for part in [
            json_dumps_safe(evidence_pool_list[:20], ensure_ascii=False),
            json_dumps_safe(rag_context_list[:20], ensure_ascii=False),
            json_dumps_safe(step_results if isinstance(step_results, dict) else {}, ensure_ascii=False),
            json_dumps_safe(debate if isinstance(debate, dict) else {}, ensure_ascii=False),
        ] if part
    )

    prompt = f"""<role>FinSight 对话/报告合成引擎 — 将原始数据转化为自然、可引用的中文分析内容</role>

<task>
根据输入数据填充报告模板变量。仅返回 JSON 对象，禁止 markdown 或注释。
所有文本值必须为简体中文。
如果 output_mode 是 chat 或 brief，字段内容要像正常对话里的分析段落：简洁、直接、有上下文感，不要套“问题/后续关注/分析对象/本轮包含”模板。
如果 inputs.conversation_router.reply_guidance 提到多个子需求或最后的收束问题，必须覆盖完整；需要一句话收束时放入 next_watch 或 conclusion。
</task>

<time_anchor>
当前日期: {current_date}
你的知识可能过时。涉及日期/发布/并购/监管等事件时，仅可使用本提示中明确提供的证据内容。
</time_anchor>

{synth_conversation_history}{synth_memory_context}<inputs>
{json_dumps_safe(inputs, ensure_ascii=False, indent=2)}
</inputs>

{realtime_section}{historical_section}{evidence_rules}<output_format>
返回 JSON 对象，键为以下模板变量的子集：
news_summary, impact_analysis, next_watch, risks,
conclusion, investment_summary, company_overview, catalysts, valuation,
price_snapshot, technical_snapshot,
comparison_conclusion, comparison_metrics,
summary, highlights, analysis.
</output_format>

<field_quality_guidelines>
每个字段的质量要求：
- company_overview: 2-3 句话概括公司主营、市场地位、核心竞争力
- catalysts: 列出 3-5 个近期催化剂，每条含事件+潜在影响；并标注事件状态【已确认】（有官方公告/日期）/【预期】（市场普遍预期未官宣）/【传言】（未经证实），如"- 【已确认】2026-06-15 财报：预期 EPS $1.2 vs 共识 $1.15"
- valuation: 包含关键估值指标（PE/PB/PS）及与历史/同业对比
- risks: 3-5 条风险要点，区分系统性风险和个股风险；每条须带可追踪触发条件（指标+阈值），禁止"宏观环境波动"类空话，如"- 毛利率风险：若毛利率跌破 40%（当前 42.3%）需重估"；缺阈值数据时标注"[阈值待补]"
- conclusion: 综合各维度给出明确的方向性判断，附条件和置信度；末尾给出具体观察点清单（指标名称+观察窗口+触发阈值+触发含义），禁止"建议持续关注"类无行动指引表述
- news_summary: 提炼核心新闻事件，侧重影响而非事件本身
- investment_summary: 一段话浓缩投资核心逻辑（多/空/中性 + 理由）
- investment_thesis: 投资主线需包含判断、依据、触发条件、证伪条件与执行建议
</field_quality_guidelines>

<constraints>
1) 严格闭卷：仅可使用 <realtime_evidence>、<historical_knowledge>、<inputs.step_results>、<inputs.evidence_ledger>、<inputs.debate> 中已出现的信息。
2) 禁止引用任何未在上述标签中出现的具体事实（尤其是产品发布时间、并购、监管进展、公司战略计划、竞争对手具体动态）。
3) 如需提及行业背景，仅允许泛化表述，禁止输出具体日期+事件断言。
4) 数据不足时明确标注"[数据缺失]"或"数据有限"，禁止补写训练知识中的细节。
5) 禁止输出原始工具数据、搜索日志、trace 信息。
6) 免责声明最多在 risks 字段末尾出现 1 次，其他字段禁止重复。
7) 每个字段控制在 6 条要点以内，追求信息密度而非长度。
8) 禁止使用"待实现"、"暂无数据"等占位短语；无数据时输出"[数据缺失]"。
9) 输出必须为合法 JSON 对象。
10) 禁止开场白、寒暄。直接输出 JSON。
11) chat/brief 模式下必须产出 conclusion 和 impact_analysis；用 2-5 条自然要点回答用户真正问的问题，报告结构只用于 investment_report。
12) chat/brief 模式下不要漏掉用户的最后一个明确请求；如果用户要求“最后/一句话/关注什么/怎么做”，用 next_watch 给出自然收束句。
13) 如 inputs.query_coverage.unanswered_targets 非空，第一段先回答已覆盖目标，并明确披露尚未覆盖的目标。
</constraints>
"""

    retry_attempts = 0

    def _on_retry(attempt: int, _exc: BaseException) -> None:
        nonlocal retry_attempts
        retry_attempts = max(retry_attempts, int(attempt))

    raw_content = ""
    try:
        await emit_event(
            {
                "type": "thinking",
                "stage": "llm_call_start",
                "message": "synthesize",
                "timestamp": utc_now_iso(),
            }
        )
        resp = await ainvoke_configured_llm(
            [HumanMessage(content=prompt)],
            context=call_context,
            temperature=_synth_temp,
            max_tokens=int(llm_limits["max_tokens"]),
            request_timeout=int(llm_limits["request_timeout"]),
            acquire_token=True,
            acquire_timeout_seconds=float(llm_limits["acquire_timeout"]),
        )
        await emit_event(
            {
                "type": "thinking",
                "stage": "llm_call_done",
                "message": "synthesize",
                "timestamp": utc_now_iso(),
            }
        )
        content = resp.content if hasattr(resp, "content") else str(resp)
        raw_content = str(content or "").strip()
        try:
            payload = json.loads(_extract_json_object(raw_content))
        except Exception:
            if output_mode in {"chat", "brief"} and raw_content and "{" not in raw_content[:120]:
                natural_text = re.sub(r"^```(?:markdown)?\s*", "", raw_content, flags=re.IGNORECASE)
                natural_text = re.sub(r"\s*```$", "", natural_text).strip()
                render_vars = _stub_render_vars(state)
                render_vars["conclusion"] = natural_text
                render_vars.setdefault("impact_analysis", natural_text)
                trace.update(
                    {
                        "synthesize": {
                            "mode": "llm",
                            "fallback": False,
                            "natural_text": True,
                            "keys": sorted(render_vars.keys()),
                            "chat_brief": True,
                            "retry_attempts": retry_attempts,
                        }
                    }
                )
                return {"artifacts": {**(state.get("artifacts") or {}), "render_vars": render_vars}, "trace": trace}
            raise
        if not isinstance(payload, dict):
            raise ValueError("render_vars payload must be a JSON object")

        payload = _coerce_payload_to_strings(payload)
        from backend.graph.render_vars.model import RenderVars

        llm_render_vars = RenderVars.model_validate(payload).model_dump()
        # Merge with deterministic stub defaults so omitted keys never fall back
        # to template placeholders. Some keys are "data sections" that must stay
        # evidence-driven; keep the stub version to avoid hallucinated metrics.
        stub_render_vars = _stub_render_vars(state)
        base_risks = str(stub_render_vars.get("risks") or "- 注：以上仅供参考，不构成投资建议。").strip()
        protected_keys = {"news_summary", "comparison_metrics", "price_snapshot", "technical_snapshot"}
        render_vars: dict[str, str] = {}
        for key, stub_value in stub_render_vars.items():
            if key in protected_keys:
                render_vars[key] = stub_value
                continue
            candidate = llm_render_vars.get(key)
            if key == "risks":
                formatted_risks = _format_risks(candidate, base_risks=base_risks)
                render_vars[key] = _scrub_unverified_future_claims(formatted_risks, llm_grounding_text)
                continue
            if key in (
                "comparison_conclusion",
                "conclusion",
                "impact_analysis",
                "next_watch",
                "investment_summary",
                "investment_thesis",
                "company_overview",
                "catalysts",
                "valuation",
                "summary",
                "highlights",
                "analysis",
            ):
                if isinstance(candidate, str) and candidate.strip():
                    candidate = _scrub_unverified_future_claims(candidate, llm_grounding_text)
                    max_lines, max_chars = _section_limits(output_mode, key)
                    sanitized = _sanitize_llm_section(candidate, max_lines=max_lines, max_chars=max_chars)
                    render_vars[key] = sanitized if sanitized else stub_value
                else:
                    render_vars[key] = stub_value
                continue

            if isinstance(candidate, str) and candidate.strip():
                candidate = _scrub_unverified_future_claims(candidate, llm_grounding_text)
                render_vars[key] = candidate
            else:
                render_vars[key] = stub_value
        for key, candidate in llm_render_vars.items():
            if key not in render_vars:
                render_vars[key] = candidate
        if any("待实现" in str(v) for v in render_vars.values()):
            raise ValueError("render_vars contains placeholder tokens")

        verifier_result: dict[str, Any]
        if output_mode == "investment_report":
            verifier_result = await _run_deep_report_verifier(
                state=state,
                generated_text="\n".join(
                    [
                        section
                        for section in (
                            str(render_vars.get("summary") or ""),
                            str(render_vars.get("highlights") or ""),
                            str(render_vars.get("analysis") or ""),
                            str(render_vars.get("investment_summary") or ""),
                            str(render_vars.get("investment_thesis") or ""),
                            str(render_vars.get("valuation") or ""),
                            str(render_vars.get("conclusion") or ""),
                            str(render_vars.get("impact_analysis") or ""),
                            str(render_vars.get("next_watch") or ""),
                            str(render_vars.get("risks") or ""),
                        )
                        if section.strip()
                    ]
                ),
                grounding_text=llm_grounding_text,
            )
        else:
            verifier_result = {
                "enabled": False,
                "checked": False,
                "reason": "chat_brief_synthesis_skips_deep_report_verifier",
                "unsupported_claims": [],
            }
        verifier_claims = (
            verifier_result.get("unsupported_claims")
            if isinstance(verifier_result, dict)
            else []
        )
        if isinstance(verifier_claims, list) and verifier_claims:
            redact_keys = (
                "summary",
                "highlights",
                "analysis",
                "investment_summary",
                "investment_thesis",
                "valuation",
                "conclusion",
                "impact_analysis",
                "next_watch",
                "risks",
            )
            for key in redact_keys:
                value = render_vars.get(key)
                if isinstance(value, str) and value.strip():
                    render_vars[key] = _apply_verifier_redactions(value, verifier_claims)
        verifier_text_after_redaction = "\n".join(
            [
                str(render_vars.get("summary") or ""),
                str(render_vars.get("highlights") or ""),
                str(render_vars.get("analysis") or ""),
                str(render_vars.get("investment_summary") or ""),
                str(render_vars.get("investment_thesis") or ""),
                str(render_vars.get("valuation") or ""),
                str(render_vars.get("conclusion") or ""),
                str(render_vars.get("impact_analysis") or ""),
                str(render_vars.get("next_watch") or ""),
                str(render_vars.get("risks") or ""),
            ]
        )
        unresolved_verifier_claims = (
            _compute_unresolved_unsupported_claims(verifier_text_after_redaction, verifier_claims)
            if isinstance(verifier_claims, list)
            else []
        )
        if isinstance(verifier_result, dict):
            verifier_result["unresolved_unsupported_claims"] = unresolved_verifier_claims

        synth_runtime: dict[str, Any] = {
            **build_runtime(mode="llm", fallback=False, retry_attempts=retry_attempts),
            "keys": sorted(render_vars.keys()),
            "llm_limits": llm_limits,
        }
        if isinstance(verifier_result, dict):
            synth_runtime["verifier_enabled"] = bool(verifier_result.get("enabled"))
            synth_runtime["verifier_checked"] = bool(verifier_result.get("checked"))
            synth_runtime["verifier_unsupported_count"] = (
                len(verifier_claims) if isinstance(verifier_claims, list) else 0
            )
            synth_runtime["verifier_unresolved_unsupported_count"] = (
                len(unresolved_verifier_claims) if isinstance(unresolved_verifier_claims, list) else 0
            )

        trace.update({"synthesize_runtime": synth_runtime})
        merged_artifacts = {**(state.get("artifacts") or {}), "render_vars": render_vars}
        if isinstance(verifier_result, dict):
            merged_artifacts["verifier_result"] = verifier_result
        if isinstance(verifier_claims, list) and verifier_claims:
            await emit_event(
                {
                    "type": "decision_note",
                    "scope": "verifier",
                    "title": "Verifier unsupported claims",
                    "reason": "Unsupported factual claims were identified in synthesis output.",
                    "impact": f"unsupported_claims={len(verifier_claims)}",
                    "timestamp": utc_now_iso(),
                }
            )
        await _emit_synth_stage_done(status="done", message="Synthesize completed")
        return {"artifacts": merged_artifacts, "trace": trace}
    except Exception as exc:
        retryable = is_rate_limit_error(exc)
        logger.warning(
            "[Synthesize] LLM call FAILED (retryable=%s, attempts=%d): %s — falling back to stub",
            retryable, retry_attempts, exc,
        )
        append_failure(
            trace,
            node="synthesize",
            stage="llm_call",
            error=str(exc),
            fallback="synthesize_stub",
            retryable=retryable,
            retry_attempts=retry_attempts,
        )
        await emit_event(
            {
                "type": "thinking",
                "stage": "llm_call_error",
                "message": "synthesize failed; fallback to stub",
                "timestamp": utc_now_iso(),
            }
        )
        render_vars = _stub_render_vars(state)
        fallback_reason = "llm_empty_output" if not str(raw_content or "").strip() else "llm_output_invalid"
        trace.update(
            {
                "synthesize_runtime": build_runtime(
                    mode="llm",
                    fallback=True,
                    reason=fallback_reason,
                    retry_attempts=retry_attempts,
                )
            }
        )
        await _emit_synth_stage_done(
            status="error",
            message="Synthesize failed, fallback to stub",
            error=str(exc),
        )
        return {"artifacts": {**(state.get("artifacts") or {}), "render_vars": render_vars}, "trace": trace}


__all__ = [
    "RenderVars",  # noqa: F822 - provided lazily by __getattr__
    "_DISALLOWED_SNIPPET_MARKERS",
    "_DISCLAIMER_PHRASES",
    "_FUTURE_DATE_PHRASE",
    "_FUTURE_EVENT_VERBS",
    "_HALLUCINATION_EVENT_PATTERNS",
    "_HALLUCINATION_SAFE_PLACEHOLDER",
    "_apply_verifier_redactions",
    "_claim_supported_by_evidence",
    "_clamp_int",
    "_coerce_payload_to_strings",
    "_compute_unresolved_unsupported_claims",
    "_contains_claim_after_redaction",
    "_env_bool",
    "_env_int",
    "_env_str",
    "_extract_brief_headline",
    "_extract_json_object",
    "_format_conversation_history_for_synth",
    "_format_memory_context_for_synth",
    "_format_risks",
    "_generate_narrative_draft",
    "_is_deep_research_run",
    "_normalize_for_match",
    "_normalize_llm_section_line",
    "_normalize_verifier_claims",
    "_run_deep_report_verifier",
    "_sanitize_llm_section",
    "_sanitize_user_facing_markdown",
    "_scrub_unverified_future_claims",
    "_section_limits",
    "_skill_perspective_block",
    "_stub_render_vars",
    "_synthesize_morning_brief_data",
    "synthesize",
]


def __getattr__(name: str) -> Any:
    """保留 ``synthesize.RenderVars``，同时避免 render_vars -> nodes 导入环。"""
    if name == "RenderVars":
        from backend.graph.render_vars.model import RenderVars

        return RenderVars
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
