# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import copy
from dataclasses import asdict, is_dataclass
import json
import logging
import os
import time
from typing import Any, Iterable, Mapping

from backend.graph.cancellation import is_cancelled
from backend.graph.event_bus import emit_event
from backend.graph.preference_timeouts import timeout_seconds_from_state
from backend.research.claim_extractor import extract_claims_from_agent_output
from backend.graph.intent.frame import AgentBrief
from backend.config.settings import agent_settings, executor_settings

logger = logging.getLogger(__name__)


def _serialize_agent_output(output: Any, *, step_name: str) -> dict[str, Any]:
    if output is None:
        return {"agent_name": step_name, "summary": "", "evidence": [], "requests": []}

    if isinstance(output, dict):
        return output

    if is_dataclass(output):
        try:
            payload = asdict(output)
            if isinstance(payload, dict):
                payload.setdefault("agent_name", step_name)
                return payload
        except Exception:
            pass

    summary = getattr(output, "summary", "")
    evidence = getattr(output, "evidence", None) or []
    confidence = getattr(output, "confidence", None)
    as_of = getattr(output, "as_of", None)
    evidence_quality = getattr(output, "evidence_quality", None)
    data_sources = getattr(output, "data_sources", None)
    fallback_used = getattr(output, "fallback_used", None)
    risks = getattr(output, "risks", None)
    trace = getattr(output, "trace", None)
    chart_specs = getattr(output, "chart_specs", None)
    requests = getattr(output, "requests", None)

    serialized_evidence: list[dict[str, Any]] = []
    for item in evidence[:12]:
        if isinstance(item, dict):
            serialized_evidence.append(item)
            continue
        if is_dataclass(item):
            try:
                serialized_evidence.append(asdict(item))
                continue
            except Exception:
                pass
        serialized_evidence.append(
            {
                "text": getattr(item, "text", None) or str(item),
                "source": getattr(item, "source", None),
                "url": getattr(item, "url", None),
                "timestamp": getattr(item, "timestamp", None),
                "confidence": getattr(item, "confidence", None),
                "title": getattr(item, "title", None),
                "meta": getattr(item, "meta", None),
            }
        )

    return {
        "agent_name": getattr(output, "agent_name", None) or step_name,
        "summary": summary,
        "confidence": confidence,
        "as_of": as_of,
        "evidence_quality": evidence_quality,
        "data_sources": data_sources,
        "fallback_used": fallback_used,
        "risks": risks,
        "trace": trace,
        "chart_specs": chart_specs if isinstance(chart_specs, list) else [],
        "evidence": serialized_evidence,
        "requests": requests if isinstance(requests, list) else [],
    }


def _classify_exception(exc: Exception) -> tuple[str, bool, str]:
    """Classify an exception into (fallback_reason, retryable, error_stage).

    Returns
    -------
    fallback_reason : str
        One of: rate_limit_timeout | execution_error | confidence_skip | budget_exceeded
    retryable : bool
    error_stage : str
        One of: token_acquire | llm_invoke | parse | tool | unknown
    """
    exc_name = type(exc).__name__.lower()
    exc_msg = str(exc).lower()

    # Timeout → likely waiting for rate-limit token
    if isinstance(exc, asyncio.TimeoutError):
        return "rate_limit_timeout", True, "token_acquire"

    # Known rate-limit / quota errors from LLM providers
    rate_limit_keywords = ("rate_limit", "ratelimit", "429", "quota", "too many requests", "resource_exhausted")
    if any(kw in exc_name or kw in exc_msg for kw in rate_limit_keywords):
        return "rate_limit_timeout", True, "llm_invoke"

    # Parse / validation errors
    parse_keywords = ("json", "parse", "decode", "validation", "pydantic", "schema")
    if any(kw in exc_name or kw in exc_msg for kw in parse_keywords):
        return "execution_error", False, "parse"

    # Tool / data source errors
    tool_keywords = ("api", "request", "connection", "http", "socket", "fetch", "tool")
    if any(kw in exc_name or kw in exc_msg for kw in tool_keywords):
        return "execution_error", True, "tool"

    # Fallback
    return "execution_error", False, "unknown"


def _build_agent_fallback_output(
    *,
    step_name: str,
    query: str,
    ticker: str,
    error: str,
    fallback_reason: str = "execution_error",
    retryable: bool = False,
    error_stage: str = "unknown",
) -> dict[str, Any]:
    safe_query = str(query or "").strip()[:160]
    safe_ticker = str(ticker or "N/A").strip().upper() or "N/A"
    safe_error = str(error or "unknown")[:300]
    summary = (
        f"{step_name} 已降级：{safe_ticker} 的分析暂不可用，"
        f"系统已返回最小可用结果（query={safe_query or 'N/A'}）。"
    )
    return {
        "agent_name": step_name,
        "summary": summary,
        "confidence": 0.2,
        "as_of": None,
        "evidence_quality": {"overall_score": 0.0, "fallback": True},
        "data_sources": ["agent_fallback"],
        "fallback_used": True,
        "fallback_reason": fallback_reason,
        "retryable": retryable,
        "error_stage": error_stage,
        "risks": [
            "当前 Agent 执行失败，结果已降级，请稍后重试。",
            f"错误摘要: {safe_error}",
        ],
        "trace": [{"event": "agent_fallback", "agent": step_name, "error": safe_error}],
        "chart_specs": [],
        "evidence": [],
        "requests": [],
    }


def _normalize_agent_output(*, step_name: str, output: Any, query: str, ticker: str) -> dict[str, Any]:
    payload = _serialize_agent_output(output, step_name=step_name)
    if not isinstance(payload, dict):
        return _build_agent_fallback_output(
            step_name=step_name,
            query=query,
            ticker=ticker,
            error="invalid_agent_output",
        )

    # 原始 Claim 是结构化 synthesis 的信任边界；外部自带 raw_claims 不可信。
    payload["raw_claims"] = copy.deepcopy(payload.get("claims")) if isinstance(payload.get("claims"), list) else []
    payload["agent_name"] = step_name

    summary = str(payload.get("summary") or "").strip()
    if not summary:
        return _build_agent_fallback_output(
            step_name=step_name,
            query=query,
            ticker=ticker,
            error="empty_summary",
        )
    payload["summary"] = summary[:5000]

    try:
        confidence = float(payload.get("confidence", 0.3))
    except Exception:
        confidence = 0.3
    payload["confidence"] = max(0.0, min(1.0, confidence))

    evidence = payload.get("evidence")
    if not isinstance(evidence, list):
        evidence = []
    payload["evidence"] = evidence[:20]

    data_sources = payload.get("data_sources")
    if not isinstance(data_sources, list):
        data_sources = []
    data_sources = [str(item).strip() for item in data_sources if str(item).strip()]
    payload["data_sources"] = data_sources or ["unknown"]

    payload["fallback_used"] = bool(payload.get("fallback_used", False))
    # Preserve structured fallback fields if present
    if "fallback_reason" not in payload:
        payload["fallback_reason"] = None
    if "retryable" not in payload:
        payload["retryable"] = None
    if "error_stage" not in payload:
        payload["error_stage"] = None
    risks = payload.get("risks")
    if not isinstance(risks, list):
        risks = []
    risks = [str(item).strip() for item in risks if str(item).strip()]
    if payload["fallback_used"] and not risks:
        risks = ["Agent 触发降级路径，建议复核关键数据。"]
    payload["risks"] = risks

    trace = payload.get("trace")
    if not isinstance(trace, list):
        payload["trace"] = []

    chart_specs = payload.get("chart_specs")
    if not isinstance(chart_specs, list):
        chart_specs = []
    payload["chart_specs"] = [
        item
        for item in chart_specs[:12]
        if isinstance(item, dict)
        and isinstance(item.get("type"), str)
        and isinstance(item.get("title"), str)
        and isinstance(item.get("data"), dict)
    ]

    requests = payload.get("requests")
    normalized_requests: list[dict[str, str]] = []
    if isinstance(requests, list):
        for item in requests[:1]:
            if not isinstance(item, dict) or str(item.get("type") or "").strip() != "delegate":
                continue
            evidence_name = str(item.get("evidence") or "").strip()[:80]
            if not evidence_name:
                continue
            normalized_requests.append(
                {
                    "type": "delegate",
                    "evidence": evidence_name,
                    "reason": str(item.get("reason") or "").strip()[:240],
                }
            )
    payload["requests"] = normalized_requests

    payload["claims"] = extract_claims_from_agent_output(payload, query=query, ticker=ticker)

    return payload


def brief_from_inputs(
    inputs: Mapping[str, Any],
    *,
    default_query: str,
    default_ticker: str,
    output_mode: str,
) -> AgentBrief:
    """从 plan step inputs 构造 AgentBrief（WP2 D4）。"""
    data = inputs if isinstance(inputs, Mapping) else {}
    query = data.get("query")
    query = str(query).strip() if isinstance(query, str) and query.strip() else default_query
    ticker = data.get("ticker")
    ticker = (
        str(ticker).strip().upper()
        if isinstance(ticker, str) and ticker.strip()
        else default_ticker
    )
    required_evidence = data.get("required_evidence")
    required_evidence = [str(item) for item in required_evidence] if isinstance(required_evidence, list) else []
    time_scope = data.get("time_scope")
    time_scope = dict(time_scope) if isinstance(time_scope, dict) else {}
    return AgentBrief(
        query=query,
        ticker=ticker,
        objective=str(data.get("objective") or ""),
        required_evidence=required_evidence,
        time_scope=time_scope,
        output_mode=str(output_mode or "chat"),
        context_digest=str(data.get("__context_digest") or ""),
    )


def _prediction_memory_context(*, user_id: str, agent: str, ticker: str) -> str:
    normalized_user = str(user_id or "").strip()
    normalized_agent = str(agent or "").strip()
    normalized_ticker = str(ticker or "").strip().upper()
    if not normalized_user or normalized_user == "public" or not normalized_agent or not normalized_ticker:
        return ""
    try:
        from backend.services.agent_prediction_store import get_agent_prediction_store

        rows = get_agent_prediction_store().prediction_history(
            agent=normalized_agent,
            ticker=normalized_ticker,
            user_id=normalized_user,
            limit=1,
        )
    except Exception:
        logger.debug("agent prediction memory unavailable", exc_info=True)
        return ""
    if not rows or not isinstance(rows[0], dict):
        return ""
    row = rows[0]
    anchor = row.get("anchor") if isinstance(row.get("anchor"), dict) else {}
    thesis = " ".join(str(row.get("thesis") or "").split())[:60]
    direction = str(row.get("direction") or "unknown")
    anchor_time = str(anchor.get("time") or "未知时间")
    anchor_price = anchor.get("price")
    levels = f"{row.get('entry')}/{row.get('stop')}/{row.get('target1')}"
    outcome = str(row.get("status") or "waiting")
    return (
        f"你上次({anchor_time})对{normalized_ticker}判断 {direction}：{thesis}；"
        f"锚点 {anchor_price}，entry/stop/T1={levels}，当前 outcome={outcome}。"
        "历史观点只作上下文，不得自动继承为本轮结论。"
    )


def _prediction_operation(*, inputs: Mapping[str, Any], state: Mapping[str, Any]) -> str:
    objective = str(inputs.get("objective") or "").strip()
    if objective:
        return objective
    if str(state.get("output_mode") or "").strip() == "investment_report":
        return "report_generation"
    operation = state.get("operation") if isinstance(state.get("operation"), dict) else {}
    return str(operation.get("name") or "").strip()


async def _maybe_submit_prediction(
    *,
    step_name: str,
    inputs: Mapping[str, Any],
    state: Mapping[str, Any],
    output: dict[str, Any],
    llm: Any,
    tools_module: Any,
) -> dict[str, Any]:
    from backend.agents.prediction_submit import (
        prediction_json_from_llm_content,
        submission_allowed,
        submit_prediction_with_async_correction,
    )

    ticker = str(inputs.get("ticker") or "").strip().upper()
    operation = _prediction_operation(inputs=inputs, state=state)
    eligible = submission_allowed(symbol=ticker, operation=operation, agent=step_name)
    output["prediction_eligible"] = eligible
    if not eligible:
        return output

    enabled = str(os.getenv("FINSIGHT_PREDICTION_SUBMIT_ENABLED", "true")).strip().lower() in {
        "1", "true", "yes", "on",
    }
    if not enabled:
        output["prediction_trace"] = {"status": "disabled", "attempts": []}
        return output

    ui_context = state.get("ui_context") if isinstance(state.get("ui_context"), dict) else {}
    user_id = str(ui_context.get("__user_id") or "").strip()
    run_id = str(ui_context.get("run_id") or state.get("run_id") or "").strip()
    fetch_bars = getattr(tools_module, "get_stock_historical_data", None)
    if not user_id or user_id == "public" or not run_id or llm is None or not callable(fetch_bars):
        output["prediction_trace"] = {"status": "prediction_missing", "attempts": []}
        return output

    try:
        raw_bars = await asyncio.to_thread(fetch_bars, ticker, period="1mo", interval="1d")
        if not isinstance(raw_bars, dict) or raw_bars.get("quality") != "trusted":
            raise ValueError("trusted market data unavailable")
        if raw_bars.get("error_code") or not raw_bars.get("provider") or not raw_bars.get("as_of"):
            raise ValueError("trusted market data provenance unavailable")
        bars = raw_bars.get("kline_data") if isinstance(raw_bars, dict) else None
        anchor_bar = bars[-1] if isinstance(bars, list) and bars and isinstance(bars[-1], dict) else None
        anchor_time = str(anchor_bar.get("time") or "").strip() if anchor_bar else ""
        anchor_price = anchor_bar.get("close") if anchor_bar else None
        if not anchor_time or anchor_price is None:
            raise ValueError("trusted anchor unavailable")
        from backend.services.agent_prediction_store import get_agent_prediction_store

        store = get_agent_prediction_store()
    except Exception:
        output["prediction_trace"] = {"status": "prediction_missing", "attempts": []}
        return output

    evidence = output.get("evidence") if isinstance(output.get("evidence"), list) else []
    evidence_titles = [
        str(item.get("title") or item.get("text") or "").strip()[:120]
        for item in evidence[:6]
        if isinstance(item, dict) and str(item.get("title") or item.get("text") or "").strip()
    ]
    from backend.services.llm_retry import LLMCallContext

    prediction_call_context = LLMCallContext.create(
        stage="agent_analyze", agent=step_name, layer="analysis", max_provider_attempts=3,
    )

    async def _generate(feedback: list[dict[str, Any]] | None) -> dict[str, Any] | None:
        from langchain_core.messages import HumanMessage
        from backend.services.llm_retry import ainvoke_configured_llm
        from backend.services.llm_usage import LLMAttribution, reset_llm_attribution, set_llm_attribution

        correction = (
            "\n上次提交未通过，必须逐项修正：\n" + json.dumps(feedback, ensure_ascii=False, default=str)
            if feedback else ""
        )
        prompt = f"""你是 {step_name}，现在必须调用一次终结工具 submit_prediction。
只返回一个 JSON 对象，不要 markdown。symbol/agent 会被服务端覆盖，但仍填写当前值。
可信最新完整 bar：timeframe=1d, time={anchor_time}, close={anchor_price}；anchor 必须原样回填。
direction 只能 long/short/neutral；confidence 0-1；thesis 最多 400 字。
long/short 必须给 entry_type(market/limit/stop)、entry、stop、target1、invalidation_price；RR>=1；target2 可选。
neutral 不得给方向价位，必须给包含 anchor 的 range_low/range_high。
scenarios 必须 2-4 条，每条含 name/probability/invalidation，概率和在 90-110。
禁止 bars/candles/series/ohlc/data/user_id/run_id。
本轮摘要：{str(output.get('summary') or '')[:1600]}
证据标题：{json.dumps(evidence_titles, ensure_ascii=False)}{correction}"""
        try:
            attribution_token = set_llm_attribution(LLMAttribution(
                agent=step_name, layer="prediction_submit",
            ))
            try:
                response = await asyncio.wait_for(
                    ainvoke_configured_llm(
                        [HumanMessage(content=prompt)],
                        context=prediction_call_context,
                        temperature=float(getattr(llm, "temperature", 0.3) or 0.3),
                    ),
                    timeout=30.0,
                )
            finally:
                reset_llm_attribution(attribution_token)
        except Exception:
            return None
        return prediction_json_from_llm_content(response)

    try:
        prediction, attempts = await submit_prediction_with_async_correction(
            _generate,
            symbol=ticker,
            agent=step_name,
            user_id=user_id,
            run_id=run_id,
            operation=operation,
            fetch_bars=lambda *_args, **_kwargs: raw_bars,
            store=store,
        )
    except Exception:
        output["prediction_trace"] = {"status": "prediction_missing", "attempts": []}
        return output
    output["prediction_trace"] = {
        "status": "submitted" if prediction is not None else "prediction_validation_failed",
        "attempts": attempts,
    }
    if prediction is not None:
        from backend.services.llm_usage import bind_current_llm_usage_prediction

        bind_current_llm_usage_prediction(agent=step_name, prediction_id=prediction.id)
        output["prediction"] = prediction.model_dump(
            mode="json", exclude={"risk_reward", "user_id", "run_id"}
        )
    return output


def build_agent_invokers(*, allowed_agents: Iterable[str], state: Mapping[str, Any]) -> dict[str, Any]:
    """
    Build best-effort invokers for legacy specialist agents.

    Node layer should call this adapter only; direct imports stay isolated here.
    """
    names = [str(n).strip() for n in (allowed_agents or []) if str(n).strip()]
    if not names:
        return {}

    try:  # pragma: no cover - runtime dependency path
        from backend.orchestration.cache import DataCache
        import backend.tools as tools_module

        from backend.agents.deep_search_agent import DeepSearchAgent
        from backend.agents.fundamental_agent import FundamentalAgent
        from backend.agents.macro_agent import MacroAgent
        from backend.agents.news_agent import NewsAgent
        from backend.agents.price_agent import PriceAgent
        from backend.agents.risk_agent import RiskAgent
        from backend.agents.technical_agent import TechnicalAgent
    except Exception:
        logger.exception("agent adapter failed to import legacy agents")
        return {}

    llm = None
    try:  # pragma: no cover - runtime dependency path
        from backend.llm_config import ConfiguredLLMHandle, get_endpoint_manager

        get_endpoint_manager()
        llm = ConfiguredLLMHandle(temperature=agent_settings().temperature)
    except Exception:
        llm = None

    cache = DataCache()
    agent_classes: dict[str, Any] = {
        "price_agent": PriceAgent,
        "news_agent": NewsAgent,
        "fundamental_agent": FundamentalAgent,
        "technical_agent": TechnicalAgent,
        "macro_agent": MacroAgent,
        "risk_agent": RiskAgent,
        "deep_search_agent": DeepSearchAgent,
    }

    subject = state.get("subject") if isinstance(state, Mapping) else {}
    subject = subject if isinstance(subject, dict) else {}
    subject_tickers = subject.get("tickers")
    subject_tickers = subject_tickers if isinstance(subject_tickers, list) else []
    default_ticker = (subject_tickers or [None])[0]
    default_ticker = (
        str(default_ticker).strip().upper()
        if isinstance(default_ticker, str) and default_ticker.strip()
        else ""
    )
    default_query = str(state.get("query") or "").strip()
    ui_context = state.get("ui_context") if isinstance(state, Mapping) else {}
    ui_context = ui_context if isinstance(ui_context, dict) else {}
    authenticated_user_id = str(ui_context.get("__user_id") or "").strip()

    policy = state.get("policy") if isinstance(state, Mapping) else {}
    policy = policy if isinstance(policy, dict) else {}
    research_config = policy.get("agent_research_config") if isinstance(policy, dict) else {}
    research_config = research_config if isinstance(research_config, dict) else {}

    agents: dict[str, Any] = {}
    init_errors: dict[str, str] = {}
    for name in names:
        cls = agent_classes.get(name)
        if not cls:
            init_errors[name] = "agent_class_not_found"
            continue
        try:
            agent_instance = cls(llm, cache, tools_module)
            if hasattr(agent_instance, "configure_research") and research_config:
                agent_instance.configure_research(
                    enable_llm_analysis=research_config.get("enable_llm_analysis"),
                    max_reflections=research_config.get("max_reflections"),
                    analysis_timeout_seconds=research_config.get("analysis_timeout_seconds"),
                    token_acquire_timeout_seconds=research_config.get("token_acquire_timeout_seconds"),
                )
            agents[name] = agent_instance
        except Exception as exc:
            logger.exception("agent adapter failed to instantiate %s", name)
            init_errors[name] = f"init_failed:{exc.__class__.__name__}"

    invokers: dict[str, Any] = {}
    preferred_timeout = timeout_seconds_from_state(state)
    execution_settings = executor_settings()
    timeout_seconds = max(
        15.0,
        preferred_timeout
        if preferred_timeout is not None
        else execution_settings.agent_invoker_timeout_seconds,
    )
    deep_search_timeout_seconds = max(
        timeout_seconds,
        execution_settings.deep_search_agent_timeout_seconds
        if execution_settings.deep_search_agent_timeout_seconds is not None
        else timeout_seconds,
    )
    max_attempts = max(1, execution_settings.agent_invoker_retry_attempts)

    for name in names:
        agent = agents.get(name)
        init_error = init_errors.get(name)

        async def _invoke(inputs: dict[str, Any], *, _agent=agent, _name=name, _init_error=init_error) -> dict[str, Any]:
            if is_cancelled():
                raise asyncio.CancelledError()
            query = inputs.get("query") if isinstance(inputs, dict) else None
            query = str(query).strip() if isinstance(query, str) and query.strip() else default_query
            ticker = inputs.get("ticker") if isinstance(inputs, dict) else None
            ticker = (
                str(ticker).strip().upper()
                if isinstance(ticker, str) and ticker.strip()
                else default_ticker
            )
            if not ticker:
                ticker = "N/A"

            await emit_event({
                "type": "agent_start",
                "agent": _name,
                "query": query,
                "ticker": ticker,
                "attempt": 1,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })

            if _agent is None:
                return _build_agent_fallback_output(
                    step_name=_name,
                    query=query,
                    ticker=ticker,
                    error=_init_error or "agent_not_available",
                )

            last_error = "unknown"
            last_reason = "execution_error"
            last_retryable = False
            last_stage = "unknown"
            for attempt in range(1, max_attempts + 1):
                if is_cancelled():
                    raise asyncio.CancelledError()
                try:
                    from backend.services.llm_usage import LLMAttribution, reset_llm_attribution, set_llm_attribution

                    invoke_timeout = (
                        deep_search_timeout_seconds if _name == "deep_search_agent" else timeout_seconds
                    )
                    brief = brief_from_inputs(
                        inputs if isinstance(inputs, dict) else {},
                        default_query=default_query,
                        default_ticker=default_ticker,
                        output_mode=str(state.get("output_mode") or "chat"),
                    )
                    memory_context = _prediction_memory_context(
                        user_id=authenticated_user_id,
                        agent=_name,
                        ticker=ticker,
                    )
                    if memory_context:
                        brief.context_digest = "\n".join(
                            item for item in (memory_context, brief.context_digest) if item
                        )
                    use_brief = agent_settings().brief_enabled
                    attribution_token = set_llm_attribution(LLMAttribution(agent=_name, layer="research"))
                    try:
                        result = await asyncio.wait_for(
                            _agent.research(query=query or "N/A", ticker=ticker, brief=brief if use_brief else None),
                            timeout=invoke_timeout,
                        )
                    finally:
                        reset_llm_attribution(attribution_token)
                    normalized = _normalize_agent_output(
                        step_name=_name,
                        output=result,
                        query=query,
                        ticker=ticker,
                    )
                    normalized = await _maybe_submit_prediction(
                        step_name=_name,
                        inputs=inputs if isinstance(inputs, dict) else {},
                        state=state,
                        output=normalized,
                        llm=getattr(_agent, "llm", None),
                        tools_module=tools_module,
                    )
                    if is_cancelled():
                        raise asyncio.CancelledError()
                    if normalized.get("summary"):
                        await emit_event({
                            "type": "agent_done",
                            "agent": _name,
                            "status": "success",
                            "confidence": normalized.get("confidence", 0),
                            "data_sources": normalized.get("data_sources", []),
                            "summary_length": len(normalized.get("summary", "")),
                            "evidence_count": len(normalized.get("evidence", [])),
                            "attempt": attempt,
                            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        })
                        return normalized
                    last_error = "empty_summary"
                    last_reason = "confidence_skip"
                    last_retryable = False
                    last_stage = "parse"
                except Exception as exc:
                    last_error = f"{exc.__class__.__name__}: {exc}"
                    last_reason, last_retryable, last_stage = _classify_exception(exc)
                    await emit_event({
                        "type": "agent_error",
                        "agent": _name,
                        "error": str(exc)[:300],
                        "error_type": exc.__class__.__name__,
                        "attempt": attempt,
                        "max_attempts": max_attempts,
                        "retryable": last_retryable,
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    })
                    if attempt < max_attempts:
                        log_fn = logger.info if last_retryable else logger.warning
                        log_fn(
                            "[AgentAdapter] %s attempt %d/%d failed (%s/%s), retrying: %s",
                            _name,
                            attempt,
                            max_attempts,
                            last_reason,
                            last_stage,
                            exc,
                        )
                        continue

            await emit_event({
                "type": "agent_done",
                "agent": _name,
                "status": "fallback",
                "fallback_reason": last_reason,
                "error": last_error[:200],
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })
            return _build_agent_fallback_output(
                step_name=_name,
                query=query,
                ticker=ticker,
                error=last_error,
                fallback_reason=last_reason,
                retryable=last_retryable,
                error_stage=last_stage,
            )

        invokers[name] = _invoke

    return invokers


__all__ = ["build_agent_invokers", "brief_from_inputs"]
